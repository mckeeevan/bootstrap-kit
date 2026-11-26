---
trigger: model_decision
description: "When and how to comment code: explain why, not what."
tools: [claude, copilot, antigravity, qwen, codex]
tier_min: small
---

# Commenting

- Default: no comment. If a better name makes the code self-explanatory, rename instead of commenting.
- Comment only to explain *why*: non-obvious business rules, algorithm choice, external constraints (rate limits, timeouts, API quirks), and regex intent.
- Never comment what the code already says (`counter++ // increment counter`), and never leave changelog or "modified by" comments.
- Never comment out dead code; delete it.
- Use standard markers sparingly: `TODO`, `FIXME`, `HACK`, `NOTE`, `WARNING`, `SECURITY` — each with a concrete reason.
- Do not name callers or users in comments ("used by the admin panel"); that rots.
