---
trigger: model_decision
description: "Unit test quality standards: falsifiable assertions, no coverage theater."
tools: [claude, copilot, antigravity, qwen, codex]
tier_min: small
---

# Unit test quality

- A test is only valuable if a wrong implementation would fail it. Before writing a test, ask: would swapping two arguments, deleting a return value, or inverting a condition be caught?
- Every test function needs at least one real assertion: `assert`, a mock verification (`assert_called_once_with`, `assert_not_called`, ...), or `pytest.raises`. A body that only calls the function under test proves nothing.
- Prefer `assert_called_once_with(...)` over `assert_called_once()`; use `ANY` only for arguments that are genuinely not the point (log strings, timestamps).
- `assert_not_called()` is only meaningful when a sibling path *does* call the mock.
- One behavior per test. Long tests with many mocks usually hide two tests.
- If the intent is "no exception raised", make that explicit in the test name and a comment — never by accident.
- Coverage measures lines executed, not behavior verified. Never add hollow assertions to satisfy a scanner; write the better test instead.
