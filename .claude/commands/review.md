---
description: Review changed files for architecture, SOLID, and test coverage
argument-hint: "[optional: path or PR description to focus on]"
---

Review the current changes against this project's rules. Focus: $ARGUMENTS

## Workflow

1. **Inspect changed files**
   - `!git status`
   - `!git diff`
   If there's no git history yet, review the files most recently written
   instead.

2. **Check architecture violations**
   - Confirm the dependency direction from @.claude/rules/architecture.md is
     respected: `app -> agent -> rag/tool -> infrastructure`, no reverse or
     skip-level imports (e.g. `agent` importing a Mongo/Redis/Qdrant client
     directly).
   - Confirm modules depend on `Protocol`/interfaces they own, not on
     concrete `infrastructure` classes.

3. **Check SOLID / code quality**
   - Single responsibility per class/function; no god objects.
   - New abstractions are justified by a real second implementation, not
     speculative (see "avoiding over-engineering" in architecture.md).
   - Full type hints, Google-style docstrings, async for I/O — see
     @.claude/rules/python-style.md.
   - FastAPI routes stay thin; Pydantic request/response models separate
     from domain models — see @.claude/rules/api-conventions.md.
   - Tool boundaries respected (typed args, description quality, no
     leaking implementation into `agent`) — see
     @.claude/rules/tool-conventions.md.

4. **Check tests**
   - New logic has unit tests against fakes/mocks at the port boundary.
   - New `infrastructure` adapters have an integration test.
   - Run `!uv run pytest` and report pass/fail, not just presence of tests.

5. **Produce a report**
   Structured as:
   - **Architecture violations** (file:line, what rule, why it matters)
   - **SOLID / quality issues** (file:line, concrete failure scenario)
   - **Test gaps** (what's untested, what could break silently)
   - **Nitpicks** (style-only, non-blocking)

   Only report what you actually verified by reading the code — no
   speculative findings. If nothing is wrong in a category, say so briefly
   rather than omitting it.
