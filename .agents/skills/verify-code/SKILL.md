---
name: verify-code
description: "Verify a change before it ships: conventions, quality, tests, and the negative paths — in that order."
---

# Verify code

A verification pass over a finished change. This is a read-mostly skill: you
run checks and report findings; you fix only what is trivially fixable, and
you report the rest.

## Inputs

- The set of changed files (from the changes file, `git diff`, or the user).
- The plan's success criteria, if a plan exists.

## Procedure

1. **Scope.** List the changed files and classify each: production code,
   tests, config, docs. Load the rules that apply to each (language rules,
   stack-pack rules).
2. **Conventions.** For each changed file, check it against the applicable
   rules: naming, structure, error handling, the stack pack's specific
   patterns (transactions, authorization, hooks discipline, ...).
3. **Quality.** Look for:
   - DRY violations introduced by the change (not pre-existing ones).
   - Error handling that swallows or misroutes failures.
   - Security: unvalidated input, secrets in code or logs, missing
     authorization on new endpoints.
   - Dead code, commented-out blocks, debug prints.
4. **Tests.** For every changed production file:
   - Is there a test that exercises the changed behavior?
   - Would a wrong implementation fail that test? (Falsifiability check.)
   - Are the negative paths tested (the 403, the empty case, the error case)?
   - Run the focused tests, then the full suite.
5. **Test execution discipline.** When running the suite:
   - Size the terminal timeout to the suite's real runtime; a suite that takes
     10 minutes needs a 15-minute timeout, not the default.
   - Always capture full output before filtering: `run-tests.sh |& tee
     output.txt`. Never pipe a long suite directly into `grep`/`tail`/`head` —
     a filtered failure is undiagnosable without a full rerun.
   - After a run, read at least 200 lines of the captured output; read more if
     failures are cut off. Do not rerun the suite to recover information it
     already produced.
   - Narrow reruns to the failing test by node ID or keyword to cut cycle
     time, still capturing output.
6. **Success criteria.** Check each criterion from the plan, one by one, and
   record pass/fail with evidence (command + output excerpt).

## Output

A report with three sections:

- **Pass** — what was checked and confirmed, with the evidence.
- **Fail** — what is broken, the exact location, and the minimal fix.
- **Skip** — what could not be verified and why (no test exists, tool
  unavailable). Never silently skip; a skip is a finding.

## Guard rails

- Do not "fix" by weakening a test or a check. If a test is wrong, say so and
  propose the corrected assertion.
- A green test run is not a pass if the tests don't cover the change.
- Report false-green risk explicitly: if a runner is unsupported or a status
  is unknown, say "unknown", not "pass".
