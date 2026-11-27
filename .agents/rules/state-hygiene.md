---
trigger: always_on
description: "Keep .claude-gui/state.yaml current: decompose todos into sub-tasks and refresh the stamp at every phase boundary."
tools: [claude, copilot, antigravity, qwen, codex]
tier_min: small
---

# State hygiene

The viewer is only as trustworthy as `.claude-gui/state.yaml`. Keep it honest.

## Decompose todos into sub-tasks

- A todo that bundles more than one deliverable (a phase with several files,
  a feature with build + test + docs) MUST be split into `children` sub-todos,
  one per deliverable. A single bullet that hides a lot of work is a bug.
- Give each sub-todo its own `id`, `text`, `status`, `owner`, and `node`
  (pointing at the structure part it belongs to).
- A parent with no status of its own is derived from its children: done when
  all are done, in_progress when any is, blocked when any is blocked.
- Keep the tree shallow: one level of sub-todos is enough; split a sub-todo
  further only if it itself hides multiple deliverables.

## Refresh the stamp at every phase boundary

- Update `todos` (statuses) AND the top-level `updated` field together, every
  time a phase or deliverable changes state. Never update one without the other.
- `updated` is the freshness gate: `setup/doctor.py` fails if the last
  `events.jsonl` entry is newer than `updated` by more than 15 minutes. A
  stale stamp is a broken install, not a cosmetic issue.
- When you finish work, the last thing you do is bring `state.yaml` current:
  flip the todos, bump `updated`, and re-run `setup/doctor.py` to confirm it
  exits 0.
