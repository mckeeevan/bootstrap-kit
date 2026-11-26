---
trigger: glob
description: "React/TypeScript conventions: typed props, hooks discipline, no any."
globs: "*.ts, *.tsx"
tools: [claude, copilot, antigravity, qwen, codex]
tier_min: small
---

# React / TypeScript

- No `any`. If a type is unknown, use `unknown` and narrow it.
- Props are typed with an explicit interface; default values in destructuring, not in the component body.
- Hooks: all hooks at top level, dependency arrays complete. A missing dependency is a bug, not a lint nit.
- Components are pure: no side effects in render. Effects for subscriptions, data fetching, and DOM.
- Keys in lists are stable IDs, never array indices.
- Errors: boundary components catch and render a fallback; never swallow in a hook.
