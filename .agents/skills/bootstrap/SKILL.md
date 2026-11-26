---
name: bootstrap
description: "Set up a fresh project for agent work: read the profile, install tool instructions, wire the viewer, produce a plan — then stop."
---

# Bootstrap

Set up a project so agents can work in it. This skill is a procedure, not a
conversation: follow the steps in order, stop where it says stop.

## Inputs

- The project description from the user (what it is, what stack it uses).
- `profile.yaml` (tools, model tier, viewer mode, stacks). If absent, create it
  from `profile.example.yaml` and ask exactly ONE question to fill the gaps.

## Procedure

1. **Read the profile.** Determine which tools to emit for and which stack
   packs apply. If the stack is unclear from the project description, ask.
2. **Dry run.** Run `setup/bootstrap.py --dry-run`. Print the plan. **Stop and
   wait for approval.** Do not continue until the user says go.
3. **Install.** Run `setup/bootstrap.py`. It clones nothing into the project,
   detects the stack, runs `sync.py`, `lint.py`, and `doctor.py`. The guard
   hook stays OFF for the entire bootstrap.
4. **Describe the project.** Read the project description and write
   `state.yaml`: `session.goal`, `structure` (3–8 parts, each with a name and
   a paths glob), and `todos` with sub-items. This is the only step where you
   write free-form content; everything else is script-owned.
5. **Verify.** Run `setup/doctor.py`. It must exit 0. If it fails, fix the
   install and re-run; do not proceed on a broken install.
6. **Enable the guard** per `profile.yaml` and start the viewer. Hand the user
   the URL.
7. **Terminal state.** Report the plan. Offer `/plan-task` or a brainstorm.
   **Do not begin implementation. Do not write application code.** An agent
   that sets up a project and keeps going is worse than one that stops.

## Division of labour

- **Script-owned** (never do these by hand): clone, stack detection, `sync.py`,
  hashes, `.gitignore`, coverage config, hook registration, port selection,
  `state.yaml` skeleton.
- **Model-owned**: project description → `structure` parts + paths globs, todo
  decomposition, stack-pack selection, `session.goal`.

## Guard rails

- One approval gate (step 2). Never skip it, never add more.
- If `doctor.py` fails twice, stop and report; do not loop.
- The viewer is read-only in tools without lifecycle hooks; say so explicitly
  rather than pretending it is live.
