---
description: Refactor code for structure/duplication while preserving behavior
argument-hint: "<path or area to refactor>"
---

Refactor: $ARGUMENTS

## Workflow

1. **Identify duplication and structural issues**
   - Read the target area in full before touching it.
   - Look for repeated logic, misplaced responsibilities (business logic in
     `infrastructure`, infra concerns leaking into `modules/*`), and
     violations of the dependency direction in
     @.claude/rules/architecture.md.
   - Note existing test coverage for this area — if it's thin, say so; a
     refactor without tests is a rewrite with extra steps.

2. **Establish a behavior baseline**
   - `!uv run pytest` before making changes, and note the result. If
     coverage is thin, add characterization tests for current behavior
     first, unless the user says not to.

3. **Improve structure**
   - Apply the smallest set of changes that removes the duplication /
     fixes the boundary violation — don't introduce a new abstraction beyond
     what's needed (see "avoiding over-engineering" in architecture.md).
   - Keep to @.claude/rules/python-style.md conventions throughout.
   - If the refactor moves code across a module boundary, update imports and
     confirm the resulting dependency direction is still valid.

4. **Preserve behavior**
   - `!uv run pytest` again after the change and confirm the same tests pass
     with no new failures.
   - Call out explicitly if any behavior intentionally changed as a side
     effect — a refactor that silently changes behavior isn't a refactor.
