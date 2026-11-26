---
trigger: manual
description: "How to write commit messages and handle branch policy."
tools: [claude, copilot, antigravity, qwen, codex]
tier_min: small
---

# Commits

See the `commit` skill for the full procedure (message format, logical grouping,
branch policy, hooks). Key invariants: imperative subject under 72 chars, every
line ≤ 80 chars, commit to the current branch (ask before `main`/`staging`),
Co-authored-by trailer when an agent contributed.
