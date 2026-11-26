---
trigger: glob
description: "Markdown authoring conventions for docs and agent files."
globs: "*.md"
tools: [claude, copilot, antigravity, qwen, codex]
tier_min: small
---

# Markdown

- Use H2/H3 for structure; reserve H1 for the document title (one per file).
- Fenced code blocks always declare a language.
- Tables for structured comparisons; bullet lists for anything enumerable.
- Keep lines under 80 characters where practical.
- Prefer short imperative sentences in instruction-style documents; state each rule once, clearly.
