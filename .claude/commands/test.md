---
description: Run the test suite, analyze failures, and suggest fixes
argument-hint: "[optional: path or -k expression to scope the run]"
---

Run and triage tests. Scope: $ARGUMENTS

## Workflow

1. **Run pytest**
   - `!uv run pytest $ARGUMENTS` (full suite if no scope given).
   - If it's a fresh project with no tests yet, say so and stop — don't
     invent test output.

2. **Analyze failures**
   For each failure:
   - Read the failing test and the code it exercises.
   - Determine whether the test or the implementation is wrong — don't
     assume the implementation is at fault by default.
   - Distinguish a real regression from an environment issue (missing
     fixture, container not running for an integration test, stale lockfile)
     and say which one it is.

3. **Suggest fixes**
   - Propose the smallest change that fixes the root cause, consistent with
     @.claude/rules/python-style.md and @.claude/rules/testing.md (unit vs
     integration boundary, mock at the port not the SDK).
   - If a fix touches a `Protocol`/port used by more than one implementation,
     flag every other implementation/test that also needs updating.
   - Apply the fix only after explaining what's broken and why the fix
     addresses it — don't silently patch and rerun without saying what
     changed.

4. **Re-run** affected tests after any fix and report the actual resulting
   output, not an assumption that it now passes.
