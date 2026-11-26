---
trigger: always_on
description: "Baseline coding discipline: minimal, surgical, standard-library-first changes."
tools: [claude, copilot, antigravity, qwen, codex]
tier_min: small
---

# Coding practices

- Solve the problem with the least code and complexity that works. No premature optimization, no speculative features.
- Prefer standard library and widely-accepted patterns. Introduce a third-party dependency only when it is the industry standard for the task.
- Make the minimum change required. Do not refactor, reformat, or "clean up" code that the task does not touch.
- Integrate new logic into the existing structure rather than replacing working blocks.
- Verify facts that could be version-dependent (APIs, library behavior, config syntax) with tools or docs instead of relying on memory.
- Explain the *why* behind non-obvious decisions in one or two sentences.
