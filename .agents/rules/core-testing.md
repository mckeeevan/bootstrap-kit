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
- Test runs must emit a machine-readable coverage report (e.g. pytest
  `--cov-report=json:coverage.json`, jest `--coverage`), configured in the
  project's test config so a plain test run always produces it. The GUI
  reads the report and shows per-part coverage; a test run without a
  coverage report leaves the map blank.
