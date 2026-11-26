---
trigger: glob
description: "Dockerfile and compose conventions: reproducible, layered, non-root."
globs: "Dockerfile*, docker-compose*.yml, compose*.yml"
tools: [claude, copilot, antigravity, qwen, codex]
tier_min: small
---

# Docker

- Pin base images by digest or explicit version tag; never `latest` in committed files.
- Order layers by change frequency: dependencies first, source last.
- Run as a non-root user in the final stage.
- One concern per stage; use multi-stage builds to keep the final image small.
- Compose files: explicit `healthcheck` for services others depend on; `depends_on` with `condition: service_healthy`, not bare service names.
- Never bake secrets into images; inject at runtime via environment or a secret manager.
