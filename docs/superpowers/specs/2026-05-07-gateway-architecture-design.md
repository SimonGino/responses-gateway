# 网关项目架构设计

**日期**: 2026-05-07
**状态**: Approved (brainstorm 完成,待 writing-plans 跟进)
**关联 issue**: [#7 — previous_response_id in SDK-only mode](https://github.com/SimonGino/responses-gateway/issues/7)
**前置文档**: [国产模型 Responses API 网关 — 现状与差距分析](./2026-05-06-chinese-models-responses-api-gap-analysis-design.md)

---

## 1. 背景与决策

国产模型 Responses 网关的架构选型有三条路径:

| 选项 | 描述 | 决定 |
|---|---|---|
| A1 | 嵌入 / Wrap LiteLLM Proxy 当后端,只暴露 `/v1/responses` 前面 | ❌ 与"轻量、SQLite 默认、可独立演进"冲突,放弃 |
| A2 | 只用 LiteLLM SDK,自建 session 存储 | ✅ **采用** |
| A3 | Vendor `litellm/responses/.../session_handler.py` | ❌ 算法本身只 ~150 LOC,不值得 vendor;反而留维护债 |

A2 内部还分 **Intercept-and-Translate** vs **Monkey-Patch** vs **Vendor**:

| 子选项 | 描述 | 决定 |
|---|---|---|
| Intercept-and-Translate | 网关在调 `litellm.aresponses` 之前自己解决 `previous_response_id` | ✅ **采用** |
| Monkey-Patch | 启动时打补丁让 `ResponsesSessionHandler` 用我们的 DB | ❌ 脆弱,要伪造 `SpendLogsPayload` |
| Vendor session_handler | 复制文件改 DB 调用层 | ❌ 同上,且 vendor 内部代码留维护债 |

**Intercept-and-Translate 的核心理由**:网关层完整掌控 session 生命周期,LiteLLM 升级不会因为内部 `session_handler` 变化而崩,未来加自定制(跨 provider tool_call_id 重映射、流式提前持久化、自定义 TTL 策略)都直接落在自己代码里。

### 决策依据

- **Q1 部署形态**: C —— 默认 SQLite 自包含,可升级 Postgres + S3
- **Q2 鉴权**: C —— 打到上游(oauth2-proxy / Cloudflare Access / Caddy),网关本身只 trust localhost / X-Forwarded-User
- **方案选择**: 1 —— Intercept-and-Translate

---

## 2. Architecture Overview

薄 FastAPI 服务,核心职责四件:**校验 reject → 拦截 previous_response_id 翻译成完整 messages → 调 `litellm.aresponses` → 落库**。

```
┌─────────┐  /v1/responses     ┌──────────────────────────────────────┐
│ Client  │ ─────────────────> │ Gateway (FastAPI)                    │
│ (Codex/ │                    │  ① Validator     (#0001 reject)      │
│  Cursor │                    │  ② SessionResolver (intercept-trans) │
│  Cline) │                    │  ③ litellm.aresponses(...)           │
│         │                    │  ④ SessionRecorder (post-call)       │
│         │ <───────────────── │  ⑤ Streaming bridge (tee+persist)    │
└─────────┘  Responses SSE     └──────────────────────────────────────┘
                                      │              │
                                      │ session rows │ large payload (optional)
                                      ▼              ▼
                                ┌──────────────┐  ┌────────┐
                                │ SQLite (def) │  │ S3/GCS │
                                │ Postgres (up)│  │ cold   │
                                └──────────────┘  └────────┘
```

边界:**LiteLLM SDK 是唯一的 LLM 依赖**。不嵌 LiteLLM Proxy、不依赖它的 Postgres/Prisma。

---

## 3. Components

| 组件 | 文件 | 职责 |
|---|---|---|
| HTTP 层 | `gateway/api.py` | FastAPI app + 路由 + 序列化 |
| Validator | `gateway/validator.py` | Per-provider per-feature 支持矩阵;reject 不支持项(#0001) |
| SessionStore | `gateway/session/store.py` | DB 抽象(SQLAlchemy 2.x async);CRUD |
| SessionResolver | `gateway/session/resolver.py` | `previous_response_id` → 重建 chat-completions messages |
| SessionRecorder | `gateway/session/recorder.py` | 调用后落库,生成新 `id`,处理 TTL/cold 阈值 |
| LLMRouter | `gateway/llm.py` | `litellm.aresponses` 薄封装;从 `models.yaml` 的 `model_list` 构建 `{alias → litellm-string}` 映射。**v1 不实例化 `litellm.Router`**(无 fallback chain / load balance / cooldown / virtual key —— 这些超出"协议层 + 状态化"的定位)。多 deployment 路由让上游 LB 处理 |
| StreamBridge | `gateway/streaming.py` | 流式事件 tee:转发到客户端 + buffer 用于落库 |
| Config | `gateway/config.py` | Pydantic Settings;YAML + env override |
| ColdStorage | `gateway/storage/cold.py` | S3/GCS offload(可选,大 payload) |

设计原则:每个组件单一职责,通过 protocol/interface 解耦,可独立测试。

---

## 4. Data Flow

### 4.1 非流式

```
1. POST /v1/responses { input, model, previous_response_id?, store?, tools?, ... }

2. Validator
   - 不支持的 tool type → 422 feature_not_supported
   - background: true → 422
   - truncation: "auto" → 422
   - presence of `conversation` → 422 conversation_not_supported
   - presence of `context_management` → 422 feature_not_supported
   - `previous_response_id` AND `conversation` 同时出现 → 422
   (具体支持矩阵见 §6 reject 列表)

3. **Generate gateway-side response id**
   new_id = "resp_" + uuid7()
   # 提前生成 —— 流式必须在 response.created 事件就拿到最终 id 给客户端,
   # 否则客户端拿到的是 LiteLLM 自己生成的 id,后续 previous_response_id 会 404

4. SessionResolver
   if previous_response_id given:
     parent = SELECT * FROM sessions WHERE id = $1
     if not parent: 404 previous_response_not_found
     if parent.ttl_at < NOW(): 410 previous_response_expired
     if parent.provider != requested_provider: 409 previous_response_provider_mismatch
     # cross-provider 不支持 (§4.3)

     # 沿 parent_id 回溯到根,而非 SELECT WHERE session_id = X
     # session_id 全量查会把分叉的 sibling 也拼进来,违反 chained linear history 语义
     chain = []
     visited = set()
     cur = previous_response_id
     while cur and cur not in visited:
       visited.add(cur)
       row = get_by_id(cur)
       if not row: break
       chain.append(row)
       cur = row.parent_id
     chain.reverse()

     messages = []
     for r in chain:
       # 重建历史时只取 user/assistant 内容,丢弃旧 instructions
       # —— OpenAI 语义:previous_response_id 不继承旧 instructions,新 instructions 是唯一 system prompt
       past_user = extract_user_input_items(r.input_json)   # 不含 instructions/system
       past_assistant = r.output_json.get("output", [])     # message + function_call items
       messages.extend(past_user)
       messages.extend(past_assistant)
     prepend messages to current input
     drop previous_response_id from request

5. LLMRouter
   # 把 model 别名(如 default-qwen)解析成 LiteLLM 标准字符串(dashscope/qwen-max)
   # —— 通过 models.yaml 的 model_list 做 alias→litellm 字符串查表,**不**实例化 litellm.Router
   model_str = alias_map.get(request_model, request_model)
   resp = await litellm.aresponses(
     model=model_str,
     input=full_input,
     **other_params,
   )
   # 不带 previous_response_id

6. (非流式) Override response id
   resp["id"] = new_id

7. SessionRecorder
   if store_flag (=请求里 store, 默认 true):
     session_id = parent.session_id if previous_response_id else uuid7()
     ttl_at = now() + config.session.default_ttl

     if size(serialize(input_json) + serialize(output_json)) > config.cold.threshold_bytes:
       try:
         cold_key = cold_storage.put({input, output})
         INSERT (id=new_id, session_id, parent_id=previous_response_id, model, provider,
                 input_json=null, output_json=null,
                 usage_json, cold_storage_key=cold_key, created_at, ttl_at)
       except ColdStorageWriteError:
         log.warn("cold storage write failed, falling back to inline")
         INSERT (id=new_id, ..., cold_storage_key=null)
     else:
       INSERT (id=new_id, ..., input_json, output_json, usage_json, cold_storage_key=null)
   else:
     # store=false: id 仍生成并返回,但不写库
     # 后续以此 id 作为 previous_response_id 必然 404 —— 符合 OpenAI "store=false 不可 retrieval" 语义
     pass

8. return resp (id 已在步骤 6 改写)
```

### 4.2 流式

步骤 1-4 同非流式(生成 new_id, validator, resolver)。

```
5. StreamBridge(rewrite_id=new_id)
   async for event in bridge.tee(litellm.aresponses(stream=True, ...)):
     # 改写以下 lifecycle 事件的 response.id → new_id:
     #   response.created / response.in_progress
     #   response.completed / response.failed / response.incomplete
     # 这样客户端从 response.created 那一刻就看到最终 id,可以立刻保存用作下次 previous_response_id
     await client.send(event)

6. (after stream end)
   final_state = bridge.final_state()
   final_state["id"] = new_id
   SessionRecorder.record(id=new_id, response_payload=final_state, ..., store_flag)
   # 与非流式同样的 store_flag 处理
```

### 4.3 跨 provider 链路 (v1 不支持)

`previous_response_id` 是 v1 强一致只在**同 provider 同 model_group**内有效:

- 父响应 provider != 当前请求 provider → **直接 409 `previous_response_provider_mismatch`**,不尝试转换
- 理由:跨 provider 续聊涉及 tool_call_id 重映射、reasoning content 跨家归一化、token 重新计费基线,工作量翻倍且语义模糊
- 上游 LiteLLM 自家也是这个策略(响应 id 编码 model_id 强制路由回同一 deployment)
- 跨 provider continuity 留 v2(单独 issue),v1 backlog #0016 第一项目标改为"明确并验证 reject 流程清晰报错"

### 4.4 store=false 语义

- `store=false` → 网关仍生成 `new_id` 并返回给客户端(响应正常)
- 但**不写 sessions 表**
- 后续以 `new_id` 作为 `previous_response_id` 调 → 走 §4.1 step 4,`get_by_id(new_id)` 返回 None → **404 `previous_response_not_found`**
- 这与 OpenAI "store=false → 响应不可 retrieval" 语义一致
- Spec §6 配置默认 `default_store: true`(用户未传 store 时默认存储)

`stream_builder` 累积:`output_text.delta`/`function_call_arguments.delta` 等增量事件 → 重建为完整 `output: OutputItem[]`,与非流式响应等价。

---

## 5. Storage Schema

单表起步。SQLAlchemy 2.x async,适配 SQLite + Postgres。

```python
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import JSON, DateTime, String
from datetime import datetime


class Base(DeclarativeBase): ...


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)         # resp_xxx
    session_id: Mapped[str] = mapped_column(String(64), index=True)       # thread / chain id
    parent_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    model: Mapped[str] = mapped_column(String(128))
    provider: Mapped[str] = mapped_column(String(64))                     # 'dashscope' / 'deepseek' / ...
    input_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    usage_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cold_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    ttl_at: Mapped[datetime | None] = mapped_column(DateTime, index=True, nullable=True)
```

**索引**: PK `id`、`session_id`、`parent_id`、`created_at`、`ttl_at`。

**Offload 规则**: 行总大小 > `config.cold.threshold_bytes`(默认 1 MB)时,把 input/output 写 S3/GCS,DB 行只存 `cold_storage_key`。读时透明重建。

**Cleanup**: 启动时执行 `DELETE FROM sessions WHERE ttl_at < NOW()`,可选注册 APScheduler / cron 周期任务。

**Migration**: 用 Alembic;每个 schema 变更一个迁移文件。

---

## 6. Configuration

`config.yaml`(env override 用 `GATEWAY_*` 前缀,Pydantic Settings 标准模式):

```yaml
storage:
  url: "sqlite+aiosqlite:///./data/sessions.db"   # 或 postgresql+asyncpg://user:pwd@host/db
  cold:
    enabled: false
    backend: "s3"                                  # s3 | gcs
    bucket_url: "s3://my-bucket/sessions"
    threshold_bytes: 1048576                       # 1 MiB

litellm:
  model_list_path: ./models.yaml                   # LiteLLM 标准 model_list 配置
  request_timeout: 60
  num_retries: 2

session:
  default_ttl_days: 30
  default_store: true                              # store=true 默认值

reject:
  tools:
    - web_search
    - web_search_preview
    - code_interpreter
    - computer_use_preview
  fields:
    background: true
    truncation: "auto"
  present_fields:                  # 这些字段只要出现就拒绝(不考虑值)
    - conversation                 # OpenAI 新加的托管会话,与 previous_response_id 互斥
    - context_management           # OpenAI 新加的上下文裁剪策略
  workaround_url_template: "https://github.com/SimonGino/responses-gateway/issues?q=is%3Aissue+{feature}"

server:
  host: "0.0.0.0"
  port: 8080
  log_level: info
  log_format: json                                 # json | console
  trust_proxy_headers: true                        # X-Forwarded-User / X-Request-Id 信任开关
```

`models.yaml` 直接复用 LiteLLM 的 `model_list` 格式(provider keys / api_base / model 名映射等),**不重新发明配置语言**。

---

## 7. Error Handling

| 情况 | HTTP | `error.type` |
|---|---|---|
| Tool / 字段不支持(reject 层) | 422 | `feature_not_supported` |
| 出现 `conversation` 字段 | 422 | `conversation_not_supported`(子类型;message 显式提示与 `previous_response_id` 二选一) |
| `previous_response_id` 不存在 | 404 | `previous_response_not_found` |
| `previous_response_id` 已过期(TTL) | 410 | `previous_response_expired` |
| 跨 provider 链断裂(parent.provider ≠ current.provider) | 409 | `previous_response_provider_mismatch` |
| LiteLLM provider 错(rate limit / auth / model down) | 透传 status code | `provider_error` 包装,保留 LiteLLM 原始 message |
| Cold storage 读失败(必须读才能重建 session) | 503 | `cold_storage_unavailable` |
| Cold storage 写失败 | 200 + warning header | 不报错,降级为内联存 DB,只 log warn |
| DB 连接失败 | 503 | `storage_unavailable` |

**所有响应带 `X-Request-Id`**(uuid7,客户端可以拿来对查日志)。

**所有日志结构化**(JSON 默认,`log_format: console` 可切人读模式),字段含:
`request_id` / `session_id` / `model` / `provider` / `latency_ms` / `error_code`(如有)。

**LiteLLM 原始错误**保留 LiteLLM 的 `error.code` / `error.type`,在我们的 `provider_error` 包装下作为 `details` 字段传给客户端。

---

## 8. Testing Strategy

| 层 | 测试方式 |
|---|---|
| Validator | Pure unit:支持矩阵驱动表(每个 provider × 每个 feature) |
| SessionResolver | Unit:合成 DB 行 → 验证 messages 重建正确;覆盖空 parent / 断链 / 跨 provider / 多模态 input |
| SessionRecorder | Unit:store=true/false、TTL 计算、cold offload 阈值边界 |
| SessionStore | Integration:in-memory SQLite + dockerized Postgres,CI 跑两套 |
| StreamBridge | 一致性:同输入下,流式重建的 final_state 与非流式响应**字节级对齐** |
| End-to-end | mock `litellm.aresponses` + 全 HTTP 流程,覆盖正常 / 各种 reject / session 重建 |
| Smoke | 每次 release tag 跑一次真实 DeepSeek 调用(成本最低) |

**CI**: GitHub Actions matrix(Python 3.11/3.12 × storage SQLite/Postgres)。Coverage gate 80%。

---

## 9. v1 Scope

### v1 必须有

- L0 协议层(全靠 LiteLLM SDK 转换)
- `previous_response_id` 状态化(自建 SessionStore + Resolver + Recorder)
- `#0001` 显式拒绝层(unsupported tools/fields)
- 配置(YAML + env)
- 结构化日志 + `X-Request-Id` 关联
- SQLite 默认 + Postgres 升级路径(同一份 SQLAlchemy 代码)
- Cold storage 接口 + S3 默认实现(可关闭)

### v1 不做(留 v2+)

- `web_search` / `code_interpreter` / `computer_use` emulation(各有专门 issue #2/#4/#5)
- 各家 provider 原生搜索开关(#3)
- 鉴权 / 多租户(打到上游反向代理)
- 后台模式 `background: true`(#6)
- 计费 / 用量聚合查询接口(usage 字段已存,但不提供查询 endpoint)
- 管理 UI
- Prometheus 指标接口(留 v2,日志足够 ship)

---

## 10. References

- Gap 分析: [`2026-05-06-chinese-models-responses-api-gap-analysis-design.md`](./2026-05-06-chinese-models-responses-api-gap-analysis-design.md)
- 相关 issues:
  - [#1 Graceful rejection of unsupported features](https://github.com/SimonGino/responses-gateway/issues/1) — v1 强依赖
  - [#7 previous_response_id in SDK-only mode](https://github.com/SimonGino/responses-gateway/issues/7) — 本设计的对应 issue
  - [#11 Verify reasoning_content field-name consistency](https://github.com/SimonGino/responses-gateway/issues/11) — 测试矩阵的一部分
  - [#14 Verify streaming usage filling](https://github.com/SimonGino/responses-gateway/issues/14) — StreamBridge 设计依据
  - [#16 Verify previous_response_id boundaries](https://github.com/SimonGino/responses-gateway/issues/16) — Resolver 设计依据
- LiteLLM 关键参考代码:
  - `litellm/responses/litellm_completion_transformation/session_handler.py:31-316` — 算法蓝本
  - `litellm/responses/litellm_completion_transformation/transformation.py:158` — 协议转换入口
  - `litellm/responses/main.py:416` — `aresponses()` SDK 入口

---

## 11. Appendix:已考虑但放弃的方案

| 方案 | 放弃原因 |
|---|---|
| A1 Wrap LiteLLM Proxy | 全套 Postgres + UI + 虚拟 key 等架构与"轻量自包含"冲突;裁剪成本高于收益 |
| A2.2 Monkey-Patch session_handler | LiteLLM 内部重构会随时打破;要伪造 `SpendLogsPayload` 类型;调试痛苦 |
| A3 Vendor session_handler | 算法只 150 LOC 不值得 vendor;留维护债;还是要伪造 `SpendLogsPayload` |
| Tornado / Sanic / aiohttp 替代 FastAPI | 生态、文档、Pydantic 集成 FastAPI 都最强;无理由换 |
| 把 model_list 设计成自家 schema | LiteLLM `model_list` 已经是社区标准,直接沿用减小学习曲线 |
