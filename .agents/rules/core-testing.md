---
trigger: always_on
description: "Core testing conventions that apply to every change."
tools: [claude, copilot, antigravity, qwen, codex]
tier_min: small
---

# Core testing

- Run the focused test for the file you changed before declaring done.
- Add a test for any new behaviour; prefer a few focused cases over coverage.
- Never delete or weaken an existing test to make a build pass.
