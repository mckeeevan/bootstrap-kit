---
name: implement-plan
description: "Execute a task plan phase by phase with TDD, updating the plan checkboxes and a changes record as you go."
---

# Implement plan

Implement a plan produced by `plan-task`. One phase at a time, tests first,
state on disk.

## Inputs

- The plan file (`plans/*.plan.md`) and its details file.
- The changes file (`changes/*.md`) — create it from the template if missing.

## Procedure

1. **Read the whole plan and the whole details file** before writing any code.
   Identify every file the plan references and read the ones that constrain
   you (interfaces, schemas, existing callers).
2. **Work one task at a time, in plan order.** For each task:
   - **RED** (new or changed behavior in a testable language): create the stub
     (`NotImplementedError` / `throw new Error`), write the test with *real*
     assertions marked as an expected failure, run it, and confirm it is
     reported as expected-failing — not passing, not erroring.
   - **GREEN**: implement the minimum that passes. Remove the
     expected-failure marker — that is the only test change. Do not edit
     assertions to make them pass.
   - **REFACTOR**: clean up for edge cases and clarity; all tests stay green.
   - Non-testable files (scripts, Dockerfiles, YAML): implement directly and
     verify by running them or their integration tests.
3. **After each task:** run the focused tests for what you touched, mark the
   checkbox `[x]`, and append to the changes file (Added / Modified / Removed,
   relative path + one sentence). If you deviated from the plan, say so in the
   changes file with the reason.
4. **Stop after each phase** and report: what changed, test results, what the
   next phase is. Continue through multiple phases only if the user asked for
   that scope up front.

## Quality bar

- Every new behavior has a test written *before* the implementation.
- A test that would pass against a wrong implementation is not a test — fix
  the assertion, not the code, when it fails for the wrong reason.
- Follow existing project patterns first; external patterns second.
- No unsolicited refactors of code the plan doesn't touch.

## Problem handling

- If a step is impossible as specified (missing dependency, wrong assumption
  in the plan), stop, record the problem in the plan file, and report it. Do
  not silently invent a workaround that changes the plan's shape.
- If context runs low mid-phase: finish the current task cleanly, update the
  plan and changes files, and report exactly where state lives so a fresh run
  can resume from the files.

## Completion

All checkboxes `[x]`, all success criteria verified, changes file has a
release summary (file inventory + overall summary). Then hand off to
`verify-code` — do not commit from this skill.
