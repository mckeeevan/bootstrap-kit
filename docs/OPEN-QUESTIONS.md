# OPEN-QUESTIONS — known-unknowns register

Work order §11. Kept live: every row is answered with a citation to a §1.4 source, or marked
**unsupported** with a documented degradation. Phase 1 (verify the unknowns) is complete —
all rows below are resolved.

## Resolved rows

### 1. Qwen Code config paths — **RESOLVED**

Qwen Code's full config surface (verified against qwen-code-docs):

| Surface | Location | Notes |
|---|---|---|
| Root instructions | `QWEN.md` (project root), `~/.qwen/QWEN.md`, `.qwen/QWEN.local.md` | `.qwen/QWEN.local.md` must be gitignored manually |
| **AGENTS.md** | project root | **Qwen reads `AGENTS.md` too** — "No need to duplicate instructions." Single shared root file works. |
| Settings | `.qwen/settings.json` (project), `~/.qwen/settings.json` (user) | JSON, layered precedence: system-defaults < user < project < system < env < CLI args |
| Skills | `.qwen/skills/*/SKILL.md` **and** `.agents/skills/*/SKILL.md` | Same open standard (agentskills.io). One canonical location works. |
| Slash commands | built-in only | **No custom slash-command file format documented.** Skills serve this role via `/<skill-name>`. |

- Source: https://qwenlm.github.io/qwen-code-docs/en/users/configuration/settings/ and the Qwen Code memory/commands pages.
- **Dedup consequence:** `AGENTS.md` is the single shared root instruction file (read by Copilot, Qwen, Antigravity). `.agents/skills/` is the single canonical skill location (read by Antigravity, Qwen, Claude Code). No per-tool root-file or skill copies needed.

### 2. Copilot `applyTo` syntax — **RESOLVED**

- `applyTo` glob syntax confirmed in `.github/instructions/*.instructions.md` frontmatter.
- **`excludeTo` does NOT exist** — the work order's "applyTo/excludeTo" is wrong. Only `applyTo` + `excludeAgent` exist (0 hits for `excludeTo` in docs.github.com search).
- Copilot reads `AGENTS.md` (nearest wins) **or** a single `CLAUDE.md` or `GEMINI.md` at repo root.
- Source: https://docs.github.com/copilot/customizing-copilot/adding-custom-instructions-for-github-copilot

### 3. Antigravity reading `CLAUDE.md` — **RESOLVED: NO**

- Antigravity reads `AGENTS.md` or `GEMINI.md` only. `CLAUDE.md` is **not** read.
- Rules: flat scan of `.agents/rules/*.md` only (nested dirs ignored unless registered in `.agents/rules.json`); 24,000-byte per-file limit; 20,000-token aggregate always-on budget; four triggers (`always_on|model_decision|glob|manual`); invalid trigger silently discarded.
- Skills: open standard (agentskills.io), `.agents/skills/` default.
- Source: https://antigravity.google/docs/rules and https://antigravity.google/docs/skills
- **Consequence:** `CLAUDE.md` must be generated as a pointer (work order §4.7 already assumes this).

### 4. game-scheduler prose quality — **OPEN (Phase 4)**

- Structure verified; prose not yet read. Work order §1.2 flags: "rewrite rather than copy blindly."
- Resolved during Phase 4 (canonical content port), not Phase 1.

### 5. Copilot lifecycle hooks — **RESOLVED: EXIST (work order row outdated)**

- The work order's "believed absent" is **wrong**. Copilot now has lifecycle hooks.
- Events use Claude-style names (`PostToolUse`, `Stop`, `SubagentStop`, etc.).
- Config locations: `.github/hooks/*.json` (repo), `~/.copilot/hooks/*.json` (user), inline `hooks` block in `.github/copilot/settings.json`. **CLI also reads cross-tool `.claude/settings.json` hooks.**
- Cloud agent: subset of events, `bash`-only, ephemeral filesystem (use `http` hook entries to retain output).
- Source: https://docs.github.com/en/copilot/reference/hooks-reference
- **Consequence:** a Copilot `events.jsonl` emitter is **feasible** (Phase 7) — the "viewer read-only in Copilot" degradation is no longer required for the CLI surface.

### 6. claude-gui license — **RESOLVED**

- No license file existed. **MIT license added** to `mckeeevan/claude-gui` this session (`LICENSE`, copyright 2026 Evan McKee).
- Viewer is pinned as an external dependency (SHA in `profile.yaml`) with a patch-set strategy — not vendored.

## Work-order errors found during Phase 1

1. **`excludeTo` does not exist** in Copilot (only `applyTo` + `excludeAgent`).
2. **Qwen Code has no custom slash-command file format** (skills serve that role via `/<skill-name>`).
3. **Copilot lifecycle hooks exist** — the "believed absent" row is outdated; a Copilot emitter is feasible.

## Dedup decisions (per user instruction: "if you find things that don't need to be double included, do that")

1. **`AGENTS.md`** = single shared root instruction file (Copilot, Qwen, Antigravity). No per-tool root duplication.
2. **`.agents/skills/`** = single canonical skill location (Antigravity, Qwen, Claude Code). No per-tool skill copies.

## Linter recommendations (added per user request)

- **Scope decision:** the kit *suggests* linters; it never installs or runs them. `lint.py` (the CI gate) stays a **config** gate only — source linting is out of scope.
- **Data file:** `stacks/linters.yaml` — 20 most common languages (python, javascript, typescript, rust, go, java, csharp, c, cpp, ruby, php, swift, kotlin, scala, dart, elixir, lua, shell, haskell, r) + 6 config-file linters (yaml, dockerfile, terraform, sql, markdown, github-actions).
- **Consumer:** `setup/doctor.py` (Phase 6) reads this and prints recommendations for the languages a project uses. Non-blocking, advisory only.
