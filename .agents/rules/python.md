---
trigger: glob
description: "Python conventions for this repo."
globs: "*.py, *_test.py"
tools: [claude, copilot, antigravity, qwen, codex]
tier_min: small
---

# Python

- Target the project's declared Python version; no version-gated hacks.
- Use type annotations on public functions.
- Prefer `pathlib.Path` over string paths.
