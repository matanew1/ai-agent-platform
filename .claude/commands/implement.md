---
description: Implement a feature end-to-end following project architecture
argument-hint: "<feature description>"
---

Implement: $ARGUMENTS

## Workflow

1. **Understand requirements**
   - Restate the feature in concrete terms: inputs, outputs, which
     module(s) it touches (`agent`/`rag`/`tool`/`infrastructure`/`app`).
   - Read the existing code in the relevant module(s) first — match its
     current patterns rather than introducing new ones.
   - If the requirement is ambiguous in a way that changes the design
     (data model, external API shape, which module owns the logic), ask
     before proceeding rather than guessing.

2. **Create an implementation plan**
   - Which files are added/changed, in which module.
   - Which port/interface (if any) this needs, and where it's defined vs.
     implemented — per @.claude/rules/architecture.md, the dependency
     direction is `app -> agent -> rag/tool -> infrastructure`.
   - Whether this needs a new `infrastructure` adapter or reuses an existing
     one.
   - For anything non-trivial, present the plan before writing code.

3. **Modify code**
   - Follow @.claude/rules/python-style.md (typing, docstrings, async, error
     handling) and, if it's an HTTP-facing change,
     @.claude/rules/api-conventions.md.
   - If it's a local tool, follow @.claude/rules/tool-conventions.md — typed
     args, real description, no implementation leaking into `agent`.
   - Keep the change scoped to what was asked; don't refactor unrelated code
     in the same pass.

4. **Add tests**
   - Unit tests against fakes/mocks at the port boundary for new logic.
   - An integration test for any new `infrastructure` adapter.
   - Run `!uv run pytest` and report the actual result.
