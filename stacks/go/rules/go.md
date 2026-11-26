---
trigger: glob
description: "Go conventions: explicit errors, small interfaces, table-driven tests."
globs: "*.go"
tools: [claude, copilot, antigravity, qwen, codex]
tier_min: small
---

# Go

- Handle every error. Wrap with `fmt.Errorf("context: %w", err)` at boundaries; check with `errors.Is`/`errors.As`.
- Small interfaces (1–3 methods) defined by the consumer, not the implementer.
- No global mutable state; configuration is passed in.
- Table-driven tests with `t.Run` subtests; use `testing.TB` helpers for cleanup.
- `context.Context` as the first parameter of any function that blocks or does I/O.
