# [verify] Vision input compatibility on Chinese VL models

**Type:** Verification task
**Priority:** P2
**Status:** ⚪ Observe
**Labels:** `type/verification` `priority/P2` `area/multimodal`

## Goal

LiteLLM transforms Responses `input_image` to chat `image_url` (`transformation.py:1073-1085`). Confirm each Chinese VL model accepts the resulting format.

## Targets

- Qwen-VL Max / Plus / Qwen2.5-VL (DashScope)
- GLM-4V / GLM-4.6V
- Doubao-Vision-Pro
- MiniMax-VL (if shipped)
- 文心 ERNIE-VL

## Test variables

- base64 vs HTTPS URL
- single image vs multi-image (max count per provider)
- max image size / pixel dimensions
- supported formats (PNG / JPEG / WEBP / GIF)
- detail level (low / high / auto — does provider honor it?)

## Tasks

- [ ] For each provider: run smoke tests with each variable matrix slot
- [ ] Document matrix in `docs/provider-matrix/vision.md`
- [ ] File follow-up issues for any provider needing custom transformation

## References

- Gap analysis: §5 item 3
- LiteLLM transform: `transformation.py:1073-1085`
