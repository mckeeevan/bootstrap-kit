---
trigger: glob
description: "GitHub Actions workflow conventions: fast, cached, least-privilege."
globs: ".github/workflows/*.yml, .github/workflows/*.yaml"
tools: [claude, copilot, antigravity, qwen, codex]
tier_min: small
---

# GitHub Actions

- Narrow `on:` triggers; a workflow that runs on every push to every branch is a workflow that wastes minutes.
- Cache dependencies and reuse the build matrix; split lint/test/build into separate jobs so failures are diagnosable.
- Least privilege: `permissions:` block scoped to the minimum the job needs; `contents: read` by default.
- Pin action versions by full SHA or tag, never a floating major.
- Fail fast: `fail-fast: true` on matrices; surface the first failure, not all of them.
- Secrets: reference via `${{ secrets.* }}` only; never echo them, never write them to logs or artifacts.
