"""Pre-call validator that rejects features the gateway can't honor.

See issue #1 (Graceful rejection of unsupported Responses API features) and
the architecture spec §7. Three rejection categories:

- Tool types in `RejectConfig.tools` (e.g. web_search, code_interpreter)
- Top-level fields whose value matches `RejectConfig.fields` (e.g. background: true)
- Top-level fields whose mere presence we reject (`RejectConfig.present_fields`,
  e.g. conversation, context_management — these are OpenAI extensions that we
  do not yet bridge and are mutually exclusive with previous_response_id)

Two modes (`RejectConfig.mode`):

- "reject" (default): raise `FeatureNotSupportedError` (→ 422). Explicit failure
  for cooperative clients.
- "strip":  remove the offending tools/fields IN-PLACE and return a list of
  (feature, param) tuples for the caller to log/return as a header. Useful for
  non-cooperative clients (Codex, Cursor) that always send `web_search` etc.
  Not a true silent-fail because the caller is expected to surface the strip
  in logs and a response header.
"""

from __future__ import annotations

from typing import Any

from gateway.config import RejectConfig
from gateway.errors import FeatureNotSupportedError


class Validator:
    def __init__(self, config: RejectConfig) -> None:
        self._cfg = config
        self._rejected_tool_types: set[str] = set(config.tools)

    def _workaround_url(self, feature: str) -> str:
        """Render the configured workaround URL with `{feature}` substituted.

        Uses string `replace()` rather than `str.format()` so user-customized
        templates with non-`{feature}` placeholders don't raise KeyError at
        validation time (turning a config typo into a 500).
        """
        return self._cfg.workaround_url_template.replace("{feature}", feature)

    def validate(
        self, request: dict[str, Any], *, provider: str | None = None
    ) -> list[tuple[str, str]]:
        """Inspect request for unsupported features.

        Returns a list of `(feature, param)` tuples that were stripped (only
        when `mode == "strip"`; empty list otherwise). Mutates `request`
        in place when stripping.

        Raises `FeatureNotSupportedError` immediately when `mode == "reject"`
        and an unsupported feature is found.
        """
        strip_mode = self._cfg.mode == "strip"
        stripped: list[tuple[str, str]] = []

        # Tools.
        tools = request.get("tools") or []
        if isinstance(tools, list):
            allow_list_active = strip_mode and bool(self._cfg.strip_mode_allowed_tool_types)
            allow_set: set[str] = (
                set(self._cfg.strip_mode_allowed_tool_types) if allow_list_active else set()
            )
            indices_to_drop: list[int] = []
            for i, tool in enumerate(tools):
                ttype = tool.get("type") if isinstance(tool, dict) else None
                # Explicit deny list (e.g. web_search): always applies.
                if ttype in self._rejected_tool_types:
                    if strip_mode:
                        stripped.append((str(ttype), f"tools[{i}].type"))
                        indices_to_drop.append(i)
                    else:
                        raise FeatureNotSupportedError(
                            feature=str(ttype),
                            param=f"tools[{i}].type",
                            provider=provider,
                            workaround_url=self._workaround_url(str(ttype)),
                        )
                    continue
                # Strip-mode allow list: drop anything not in the allow set.
                # E.g. Codex sends `namespace` tools; chat/completions providers
                # 400 on unknown types. Reject mode does NOT apply this — it's a
                # safety net specifically for non-cooperative clients.
                if allow_list_active and isinstance(ttype, str) and ttype not in allow_set:
                    stripped.append((ttype, f"tools[{i}].type"))
                    indices_to_drop.append(i)
            for i in reversed(indices_to_drop):
                tools.pop(i)
            if not tools and "tools" in request:
                # Empty tools list can confuse some providers; remove the key entirely.
                request.pop("tools", None)

        # Fields rejected by exact value match (e.g. background: true, truncation: "auto")
        for field, rejected_value in self._cfg.fields.items():
            actual = request.get(field)
            hit = (
                actual is rejected_value
                if isinstance(rejected_value, bool)
                else (actual == rejected_value)
            )
            if hit:
                if strip_mode:
                    stripped.append((field, field))
                    request.pop(field, None)
                else:
                    raise FeatureNotSupportedError(
                        feature=field,
                        param=field,
                        provider=provider,
                        workaround_url=self._workaround_url(field),
                    )

        # Fields rejected purely by presence (e.g. conversation, context_management)
        for field in self._cfg.present_fields:
            if field in request and request[field] is not None:
                if strip_mode:
                    stripped.append((field, field))
                    request.pop(field, None)
                else:
                    raise FeatureNotSupportedError(
                        feature=field,
                        param=field,
                        provider=provider,
                        workaround_url=self._workaround_url(field),
                    )

        return stripped
