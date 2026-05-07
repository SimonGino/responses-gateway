"""Pre-call validator that rejects features the gateway can't honor.

See issue #1 (Graceful rejection of unsupported Responses API features) and
the architecture spec §7. Three rejection categories:

- Tool types in `RejectConfig.tools` (e.g. web_search, code_interpreter)
- Top-level fields whose value matches `RejectConfig.fields` (e.g. background: true)
- Top-level fields whose mere presence we reject (`RejectConfig.present_fields`,
  e.g. conversation, context_management — these are OpenAI extensions that we
  do not yet bridge and are mutually exclusive with previous_response_id)
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

    def validate(self, request: dict[str, Any], *, provider: str | None = None) -> None:
        """Raise FeatureNotSupportedError if request contains unsupported features."""
        # Tools
        tools = request.get("tools") or []
        for i, tool in enumerate(tools):
            ttype = tool.get("type") if isinstance(tool, dict) else None
            if ttype in self._rejected_tool_types:
                raise FeatureNotSupportedError(
                    feature=ttype,
                    param=f"tools[{i}].type",
                    provider=provider,
                    workaround_url=self._workaround_url(ttype),
                )

        # Fields rejected by exact value match (e.g. background: true, truncation: "auto")
        for field, rejected_value in self._cfg.fields.items():
            actual = request.get(field)
            if isinstance(rejected_value, bool):
                if actual is rejected_value:
                    raise FeatureNotSupportedError(
                        feature=field,
                        param=field,
                        provider=provider,
                        workaround_url=self._workaround_url(field),
                    )
            else:
                if actual == rejected_value:
                    raise FeatureNotSupportedError(
                        feature=field,
                        param=field,
                        provider=provider,
                        workaround_url=self._workaround_url(field),
                    )

        # Fields rejected purely by presence (e.g. conversation, context_management)
        for field in self._cfg.present_fields:
            if field in request and request[field] is not None:
                raise FeatureNotSupportedError(
                    feature=field,
                    param=field,
                    provider=provider,
                    workaround_url=self._workaround_url(field),
                )
