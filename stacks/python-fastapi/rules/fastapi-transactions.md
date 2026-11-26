---
trigger: glob
description: "FastAPI transaction and session discipline for route handlers and services."
globs: "*.py"
tools: [claude, copilot, antigravity, qwen, codex]
tier_min: small
---

# FastAPI transactions

- Route handlers own the unit of work: open the session/transaction in the handler (or a dependency), commit on success, roll back on any exception. Services receive the session; they never open or commit one.
- Never commit inside a service function. A service that commits makes the handler's rollback path dead code.
- Never mix a long-running external call (HTTP, queue publish) inside an open transaction. Commit first, then call out; a slow dependency holds locks and connections.
- Read-only endpoints do not need a commit, but they still need a close; use the same dependency so the pattern is uniform.
- When a handler must publish an event after committing, publish *after* the commit — an event for a rolled-back write is a lie.
