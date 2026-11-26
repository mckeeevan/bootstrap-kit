---
trigger: always_on
description: "Never bypass quality checks, linters, or tests without explicit user approval."
tools: [claude, copilot, antigravity, qwen, codex]
tier_min: small
---

# Quality checks

- Never bypass, suppress, or weaken a quality check (pre-commit hook, linter, type checker, test) without explicit user approval.
- Prohibited without approval: `git commit --no-verify`, `SKIP=<hook>`, `# noqa`, `# type: ignore`, `// @ts-ignore`, `eslint-disable`, `@pytest.mark.skip`, loosening thresholds in config files.
- When a check fails, fix the code first. If an override is genuinely necessary, present the issue, the alternatives considered, and ask for approval before proceeding.
- "The check is annoying", "it's faster to skip", and "the code works fine" are not valid reasons.
- Never delete or weaken an existing test to make a build pass.
