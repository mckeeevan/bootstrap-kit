# BOOTSTRAP.md — the contract

This is the **only** file an agent reads first. It is ordered and **terminating**:
follow the steps in order, and stop at step 7. An agent that sets up a project
and keeps going is worse than one that stops.

## The 7 steps

1. **Read `profile.yaml`.** If it is absent, copy `profile.example.yaml` to
   `profile.yaml` and ask the user **one** question: which tools and model tier
   do they use? Do not ask more.

2. **Run `python3 setup/bootstrap.py --dry-run`.** Print the plan it produces.
   **STOP and wait for approval.** Do not proceed until the user says go.

3. **Run `python3 setup/bootstrap.py`.** This is the script-owned install:
   clone the pinned `claude-gui` → detect the stack → `sync/sync.py` →
   `sync/lint.py` → write the `.claude-gui/` state skeleton.
   **The guard hook stays OFF for the entire bootstrap.** Do not enable it here.

4. **Read the project. Write `state.yaml`.** This is the model-owned part.
   Fill in `.claude-gui/state.yaml`:
   - `session.goal` — one sentence, what the project is for.
   - `structure` — 3–8 parts, each with a `paths` glob that matches real files.
   - `todos` — the decomposed plan, with sub-items where a step is non-trivial.
   - `session.thinking` — a short note on the approach.
   Do **not** invent parts that have no files; the viewer drops empty parts.

5. **Run `python3 setup/doctor.py`.** It must exit `0`. If it reports a
   problem, fix it and re-run. Doctor is read-only and safe to re-run.

6. **Enable the guard per `profile.yaml`.** Set the guard `enabled: true` in
   `.claude-gui/guard.yaml` (mode from `profile.yaml viewer.guard`). Start the
   viewer and hand the user the URL.

7. **TERMINAL STATE.** Report the plan back to the user and offer
   `/plan-task` or `/brainstorm`. **Do not begin implementation. Do not write
   application code.** The setup is done; the work has not started.

## Division of labour

**Script-owned** (deterministic, in `setup/` + `sync/`): clone, stack
detection, `sync.py`, hashes, `.gitignore`, coverage config, hook
registration, port selection, the `state.yaml` skeleton.

**Model-owned** (judgment, in `state.yaml`): project description → `structure`
parts + `paths` globs, todo decomposition, stack-pack selection,
`session.goal` / `session.thinking`.

The scripts never write application code and never decompose todos. The model
never edits generated files by hand (re-run `sync.py` instead) and never
enables the guard before step 6.
