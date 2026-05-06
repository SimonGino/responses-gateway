# 国产模型 Responses API 网关 — 现状与差距分析

**日期**: 2026-05-06
**状态**: Draft for review
**范围**: 评估通过 LiteLLM 给国产 LLM(千问 / DeepSeek / Moonshot / 智谱 / 豆包 / MiniMax / 文心 / 混元 等)套上 OpenAI Responses API 协议的可行性,梳理可无伤跑通的能力 vs 必须自行适配的差距。

---

## 1. 背景与目标

OpenAI 在 Responses API 引入了若干 Chat Completions 没有的概念:有状态会话(`previous_response_id`)、内置工具(`web_search` / `file_search` / `code_interpreter` / `computer_use`)、显式的 reasoning 输出项、结构化的流式事件。客户端越来越多地直接用 Responses 协议(Cursor、Cline、Codex CLI、ChatGPT Apps SDK 等),需要一个网关把 Responses 协议转给国产模型。

本文**只回答**:

1. 两套协议的字段级差异是什么?
2. 哪些能力**今天**就能通过 LiteLLM 无伤透传到国产模型(只做协议转换、网关里**不需要**跑额外 runtime)?
3. 哪些能力 LiteLLM 还没解决,后续需要单独适配?

**显式 out of scope**(留给后续 spec):

- 网关项目的具体架构选型(Wrap LiteLLM Proxy / SDK-only / Fork)
- 差距能力的实现策略(自托管 emulation vs 各家原生协议适配 vs 混合)
- 运维能力设计(鉴权、限流、计费、可观测性)
- `computer_use` 在国产模型上的可行性研究

---

## 2. 协议对比:Chat Completions vs Responses API

### 2.1 请求结构

| 字段 / 概念 | Chat Completions | Responses API |
|---|---|---|
| 输入正文 | `messages: ChatMessage[]`,角色 `system / user / assistant / tool` | `input: string \| InputItem[]`(可纯字符串、消息数组、或包含 tool_result 的混合数组) |
| 系统提示 | 第一条 `role: "system"` 消息 | 顶层独立字段 `instructions: string` |
| 模型 | `model` | `model` |
| 工具定义 | `tools: [{type: "function", function: {name, description, parameters}}]` —— 嵌套 | `tools: [{type: "function" \| "web_search" \| "file_search" \| "code_interpreter" \| "computer_use_preview" \| "mcp", ...}]` —— 平铺,字段在顶层 |
| 工具选择 | `tool_choice: "auto" \| "none" \| "required" \| {type:"function", function:{name}}` | `tool_choice: "auto" \| "none" \| "required" \| {type:"function", name} \| {type:"web_search"} \| {type:"file_search"} \| ...` |
| 历史会话 | 完全靠客户端在 `messages` 里携带 | 可选 `previous_response_id` —— 服务端从过去的 response 重建 |
| 持久化 | 无 | `store: bool`(默认 `true`)—— 是否落库供后续 `previous_response_id` 引用 |
| 输出格式 | `response_format: {type: "json_object" \| "json_schema", ...}` | `text: {format: {type, name, schema, strict}}` |
| 后台模式 | 无 | `background: bool` —— 异步执行,客户端 GET `/responses/{id}` 拉结果 |
| 截断 | 无标准字段 | `truncation: "auto" \| "disabled"` |
| 流式 | `stream: bool` | `stream: bool` |
| 流式 usage | `stream_options: {include_usage: bool}` | 自动包含在 `response.completed` 事件 |
| 推理预算 | 无标准字段(各家自定义,如 `reasoning_effort`) | `reasoning: {effort: "low"\|"medium"\|"high", summary: "auto"\|"concise"\|"detailed"}` |
| max tokens | `max_tokens` / `max_completion_tokens` | `max_output_tokens` |
| 元数据 | `metadata: {...}`(部分 provider) | `metadata: {...}`(标准化) |
| 用户标识 | `user: string` | `user: string` |
| 并行工具 | `parallel_tool_calls: bool` | `parallel_tool_calls: bool` |

### 2.2 输出结构

| 字段 / 概念 | Chat Completions | Responses API |
|---|---|---|
| 顶层结果 | `choices[]` 数组(通常长度 1) | `output: OutputItem[]` —— 数组内是有序的项目流 |
| 文本回复 | `choices[0].message.content: string` | `OutputItem{type: "message", role: "assistant", content: [{type: "output_text", text, annotations}]}` |
| 工具调用 | `choices[0].message.tool_calls: [{id, type, function:{name, arguments}}]` | `OutputItem{type: "function_call", id, call_id, name, arguments}` |
| 推理内容 | `choices[0].message.reasoning_content`(非标准,各家命名不一致) | `OutputItem{type: "reasoning", id, summary, content}` |
| 内置工具调用 | (没有概念) | `OutputItem{type: "web_search_call" \| "file_search_call" \| "code_interpreter_call", ...}` |
| 引用 / 标注 | (没有概念) | `output_text.annotations: [{type:"file_citation",...} \| {type:"url_citation",...}]` |
| 完成原因 | `choices[0].finish_reason: "stop"\|"length"\|"tool_calls"\|...` | `status: "completed"\|"in_progress"\|"incomplete"\|"failed"\|"cancelled"` + 可选 `incomplete_details` |
| 用量 | `usage: {prompt_tokens, completion_tokens, total_tokens}` | `usage: {input_tokens, output_tokens, total_tokens, output_tokens_details:{reasoning_tokens}}` |
| ID | `id`(单次请求) | `id`(可被后续请求作为 `previous_response_id` 引用) |

### 2.3 流式事件

| Chat Completions | Responses API |
|---|---|
| 单一 chunk schema:`{choices:[{delta:{content, tool_calls}}]}` —— 状态靠 delta 字段判断 | 多种 typed event,每个 event 顶层带 `type`:`response.created` / `.in_progress` / `.output_item.added` / `.content_part.added` / `.output_text.delta` / `.output_text.done` / `.function_call_arguments.delta` / `.function_call_arguments.done` / `.output_item.done` / `.completed` / `.failed` / `.incomplete` |
| 流终止靠 `data: [DONE]` 哨兵 | 流终止靠 `response.completed` event |
| Tool call 靠客户端按 `tool_calls[i]` 的索引拼 delta,识别开始 / 结束 | 服务端显式发 `output_item.added`(开始)和 `.done`(结束),客户端不用猜 |
| Usage 在 `stream_options:{include_usage:true}` 时作为最后一个 chunk | Usage 在 `response.completed` 事件中 |

### 2.4 关键能力差异总结

- **状态化**: Responses 是 Chat 的**有状态超集**。Chat stateless,Responses 默认 stateful(`store:true` 默认值)
- **工具语义**: Responses 把"模型能用的工具"分两类
  - **客户端工具**(`function`):客户端执行后回填 `function_call_output`,跟 Chat 一样
  - **服务端工具**(`web_search` / `file_search` / `code_interpreter` / `computer_use`):**OpenAI 服务端代为执行**,客户端只看到 `*_call` 输出项
  - Chat 只有客户端工具一种概念
- **推理结构化**: Responses 把推理升级为一等输出项 + 标准化 token 计量;Chat 各家有各家的非标准字段
- **流式可追踪**: Responses 流式事件有明确的 `output_item.added` / `.done`,客户端无需 reassemble delta

---

## 3. 国产模型上 LiteLLM 可无伤跑通的能力

下面这些 LiteLLM 已经在 `LiteLLMCompletionTransformationHandler` 里做了完整双向翻译,**对所有走 chat/completions 的国产 provider 都生效**(DashScope、DeepSeek、Moonshot、Volcengine 豆包、MiniMax、智谱兼容路径 等)。

也就是说调用 `litellm.responses(model="dashscope/qwen-max", input=...)` 就能直接跑。

| 能力 | LiteLLM 实现位置 | 备注 |
|---|---|---|
| `input` ↔ `messages` 互转 | `responses/litellm_completion_transformation/transformation.py:158` | 字符串 input、消息数组、tool result 项都规整到 messages |
| `instructions` → system message | 同上 | 自动拼成第一条 `role:"system"` |
| Function tool 双向转换 | `transformation.py:1352` | Responses 的扁平 schema → Chat 的嵌套 `{function:{...}}`,双向通 |
| `tool_choice` 转换 | `transformation.py:106` | 包括 Cursor IDE 的 `{"type":"tool"}` 这种特殊格式 |
| Reasoning 内容透传 | `transformation.py:1807-1833` (`_extract_reasoning_output_items`) | 模型返回 `reasoning_content` 时自动包成 `{type:"reasoning"}` 输出项,DeepSeek-R1 / QwQ / GLM-Zen / Doubao-thinking 都依赖此路径(**但字段名一致性需验证,见 §5**) |
| 流式事件发射 | `responses/litellm_completion_transformation/streaming_iterator.py:47` | 把 Chat chunk 翻译成完整 Responses 事件流(`response.created` → `output_text.delta` → `function_call_arguments.delta` 按 10 字符分片 → `completed`) |
| `previous_response_id` | `responses/litellm_completion_transformation/session_handler.py:31` | 从 `LiteLLM_SpendLogs`(Postgres) + cold storage 重建 messages —— **强依赖 LiteLLM Proxy + Postgres**;只用 SDK 不行 |
| `store: true / false` | 同上 | 通过 spend_logs 持久化 |
| `file_search` 工具 | `responses/file_search/emulated_handler.py` | 注入 `litellm_file_search` function tool → 模型 function call → 调 `litellm.vector_stores.asearch()` → 包回 `file_search_call` + `file_citation` annotations。**对所有 provider 都通**,前提是接了 vector store(LiteLLM 支持 OpenAI / Pinecone / Qdrant / Bedrock KB 等) |
| `mcp` 工具 | `transformation.py:1368` | 透传给底层 chat tools(provider 是否识别取决于自身) |
| `max_output_tokens` → `max_tokens` | `transformation.py` | 字段重命名 |
| `input_image` / `image_url` 视觉输入 | `transformation.py:1073-1085` | `input_image` 和 `image_url` 都转成 chat 的 `image_url` block;**协议层 OK**,运行时各家 provider 接受度需逐一验证 |
| `parallel_tool_calls` | 直接透传 | 大多数 OpenAI 兼容路径支持 |
| 通用参数(`temperature`、`top_p`、`stop`、`seed` 等) | 直接透传 | provider-by-provider |
| Cost 计算 | `cost_calculator.py:1019` | 用 `model_prices_and_context_window.json`,主流国产模型大部分都有价格条目 |
| JSON / structured output | 通过 `text.format` → `response_format` 翻译 | 取决于 provider 是否支持 JSON 模式 |
| 流式 usage | 自动桥接到 `stream_options:{include_usage:true}` | LiteLLM Proxy 还有 `always_include_stream_usage` 全局开关 |

---

## 4. 国产模型上 LiteLLM **现不能开箱跑通**的能力

下面这些是 LiteLLM 现有版本的**真实差距 —— 上游就还没实现**,不是配置问题。

| 能力 | 问题 | 影响范围 |
|---|---|---|
| **`web_search` 内置工具** | `transformation.py:1371-1384` 只把它转成 OpenAI 的 `web_search_options` 字段然后透传。国产 provider 都不认识这个字段,直接忽略;LiteLLM **没有 emulation runtime**(file_search 有,web_search 没有) | 所有非 OpenAI / Perplexity 系 provider |
| **`code_interpreter` 内置工具** | `transformation.py:1779` 只解析下游返回的 `code_interpreter_call` 输出项,**没有沙箱执行能力**。国产模型不会主动产出这种字段 | 所有国产 provider |
| **`computer_use_preview`** | 仅在 `llms/vertex_ai/gemini/...:377` 走通(`_transform_computer_use_config`);非 Vertex 的全军覆没 | 所有国产 provider |
| **各家原生搜索开关** | Qwen 的 `extra_body.enable_search`、智谱的 `tools[type=web_search]`、Moonshot 的 `$web_search` builtin function、豆包的应用入口 —— LiteLLM 全部没对接(在 `litellm/llms/dashscope/` `moonshot/` `volcengine/` `minimax/` `deepseek/` 里 grep `enable_search` / `web_search` 均 0 命中) | 想用厂商自带搜索而不是 emulation 的场景 |
| **后台模式 `background: true`** | `litellm/responses/` 全目录 grep `background.*true / background_mode / is_background` 0 命中。**完全没实现** | 所有 provider(国产 + 国外都受影响) |
| **`previous_response_id` 在 SDK-only 模式** | 该能力强依赖 LiteLLM Proxy 的 `LiteLLM_SpendLogs` + Postgres + cold storage;不跑 Proxy 就要自己实现等价存储 | 想走轻量 SDK 集成的场景 |
| **`truncation: auto`** | `transformation.py` 中只在响应侧透传 `truncation` 字段(line 1692),**输入端的 `truncation:auto` 被忽略**,不会触发任何裁剪行为 | 输入超长时的兜底 |
| **GET `/v1/responses/{id}` / DELETE / cancel 端点的真实状态** | LiteLLM Proxy 有 `response_polling/`(异步流恢复),但完整的 Responses CRUD 端点对国产 provider 没意义 —— 下游不存。LiteLLM 是从 `spend_logs` 反查 | 需要状态查询的客户端(部分 IDE) |
| **Annotations 完整性** | `output_text.annotations` 中的 `file_citation` 在 file_search emulation 下能产出;`url_citation`(由 web_search 产生)目前**没有路径**能产生 | 引用展示场景 |

---

## 5. 待验证项(需要继续读源码或跑实验确认)

下面这些点**没在代码里直接确认**,落地前需要验证:

1. **`reasoning_content` 在国产 reasoning 模型上的字段一致性**
   - DeepSeek-R1 用 `reasoning_content`(已对齐)
   - Qwen QwQ 在 DashScope 是否也叫这个名?
   - GLM-Zen / Doubao-thinking / Hunyuan-T1 呢?
   - 字段名不同时 LiteLLM 的 `_extract_reasoning_output_items()` 取不到,reasoning 输出项就是空的

2. **`response_format` / structured output 在国产 provider 上的覆盖度**
   - 哪些国产模型支持 `json_object` / `json_schema`?
   - 不支持时 LiteLLM 是直接报错还是降级为提示词约束?

3. **多模态视觉输入在各家的真实通过率**
   - LiteLLM 协议层把 `input_image` 转成 chat 的 `image_url` block(已确认)
   - DashScope-VL / GLM-V / Doubao-Vision / Qwen-VL 各家对 base64 vs URL 的支持、对图像数量限制是否一致

4. **流式 usage 字段填充**
   - 国产 provider 流式最后一个 chunk 是否真的带 usage?如果没有,LiteLLM 会触发本地 `token_counter` 兜底,但精度依赖 tokenizer 选择是否准确

5. **`background: true` 报错行为**
   - LiteLLM 收到这个字段会怎么样?静默忽略?报 NotImplemented?还是抛 422?需要确认对客户端的可见行为

6. **MCP tool 在 Chat Completions 国产 provider 上的真实行为**
   - 透传的 `mcp` 字段下游能不能识别;不能识别时 LiteLLM 是否做了降级处理(转成普通 function tool?直接丢弃?)

7. **`previous_response_id` 在 Proxy + Postgres 场景下的边界**
   - 跨 provider / 跨 model 切换时 session 重建是否仍然准确?
   - 历史消息超过新模型上下文窗口时的行为?
   - `LiteLLM_SpendLogs` 的留存策略 / 索引 / 清理工具

---

## 6. 后续(显式 Out of Scope)

下面留给后续 spec,不在本文讨论:

- **怎么补 §4 的差距**:OpenAI 风格自托管 emulation(复用 `file_search` 的做法做 `web_search` 和 `code_interpreter`) vs 逐家适配 provider 原生搜索 vs 混合
- **网关项目的具体架构**:FastAPI vs 别的;LiteLLM Proxy 当后端 vs 只用 SDK;会话存储用什么(沿用 LiteLLM Proxy 的 spend_logs vs 自建表)
- **运维能力设计**:鉴权、限流、计费日志、配置热加载、Prometheus 指标、结构化日志
- **`computer_use` 在国产模型上的可行性**:这是研究问题,先做 §5 的验证再说

---

## 附录 A:关键文件快速索引

| 用途 | 文件 |
|---|---|
| 协议双向转换主入口 | `litellm/responses/litellm_completion_transformation/transformation.py` |
| 流式事件转换 | `litellm/responses/litellm_completion_transformation/streaming_iterator.py` |
| `previous_response_id` 重建 | `litellm/responses/litellm_completion_transformation/session_handler.py` |
| `file_search` emulation | `litellm/responses/file_search/emulated_handler.py` |
| Responses API 公开端点(Proxy) | `litellm/proxy/response_api_endpoints/endpoints.py` |
| Responses SDK 入口 | `litellm/responses/main.py:901` `responses()` / `:416` `aresponses()` |
| Provider responses config 注册表 | `litellm/utils.py:8602-8630` |
| Cost 计算 | `litellm/cost_calculator.py:1019` `completion_cost()` |
| 价格表 | `model_prices_and_context_window.json` |

## 附录 B:相关参考(本机已有)

- `~/Code/GitHub/litellm-codex-gateway-guide.md` —— 之前写的 LiteLLM Proxy 给 Codex CLI 接 chat backend 的部署指南
- `~/Code/GitHub/open-responses-server` —— 同领域的开源参考项目
