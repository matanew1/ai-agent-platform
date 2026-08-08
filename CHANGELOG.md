# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[Semantic Versioning](https://semver.org/) once there's a published API to
version against - starting at `0.1.0` for this first tracked release.

Releases are cut with `npx standard-version` (config in `.versionrc.json`),
which builds the sections below from [Conventional
Commits](https://www.conventionalcommits.org/) - so a commit's `feat:` /
`fix:` prefix is what puts it in this file. Note that below `1.0.0` a
`feat:` bumps a patch, not a minor: pass `--release-as minor` when a
release deserves one.

## [0.2.0](https://github.com/matanew1/ai-agent-platform/compare/v0.1.0...v0.2.0) (2026-08-07)


### Added

* **tool:** add MCP server support with fetch and time servers ([6b4de24](https://github.com/matanew1/ai-agent-platform/commit/6b4de2455107cd72a1ab4899577b926d7dcf7a73))


### Fixed

* **llm:** raise on an empty completion instead of returning it as an answer ([4d79083](https://github.com/matanew1/ai-agent-platform/commit/4d79083167cb6b9cf70a33c324847e4852b83758))

## [0.1.0] - 2026-08-07

Initial tracked release - `agent`, `rag`, and `tool` are all fully
implemented and verified against live services (real Ollama/Mistral, real
Qdrant, real local tool extraction), not just unit-tested. See
`README.md` and `.claude/rules/` for the full architecture and
conventions.

### Added

- FastAPI application (`app/`) with a `lifespan`-based composition root:
  builds MongoDB, Redis, Qdrant, and the configured LLM provider adapters
  and wires them into `agent`/`rag`/`tool` module services exactly once
  per process.
- `agent`: a LangGraph workflow (`retrieve_context` ∥ `execute_tools` ->
  `generate_answer`) behind `POST /chat` and `POST /chat/stream`, with
  conversation history persisted to Redis (`agent_session:{session_id}`),
  a 7-day TTL on idle sessions, and a distributed lock
  (`memory.session_lock`) guarding against two concurrent requests on the
  same session racing each other and silently dropping a turn.
- `rag`: document ingestion (`POST /rag/documents`, `POST
  /rag/documents/file` for txt/pdf/docx) and retrieval (`POST
  /rag/search`) against a real Qdrant collection - retrieval returns no
  context (not an error) when the collection doesn't exist yet, and uses
  it normally once it does.
- `tool`: a local tool registry (`@mcp_tool` decorator) with PDF and
  Markdown text-extraction tools; the agent calls tools by name and typed
  arguments without knowing their implementation.
- Two selectable LLM providers behind one `LLMProvider` port
  (`LLM_PROVIDER=ollama|mistralai`): local Ollama (`qwen3:8b` default) or
  the remote Mistral AI API (`mistral-small-latest`, free-tier eligible).
- Workflow efficiency passes: heuristic skips for tool-selection
  (`_mentions_a_tool`) and retrieval (`_is_smalltalk`) on turns that
  plainly don't need them, and `OLLAMA_KEEP_ALIVE` to avoid repeated
  local model loads between chat turns.
- Unit test suite (`tests/`) covering `agent`/`rag`/`tool` against
  hand-written fakes satisfying each module's `Protocol` ports, including
  regression coverage for the session-lock concurrency fix.

### Known gaps

- `infrastructure/database.py`'s CRUD methods (`find_one`/`insert_one`/
  `update_one`) are still `NotImplementedError` stubs - nothing in the
  current request path calls them yet; `connect`/`close` are real.
- No committed integration tests against real Mongo/Redis/Qdrant/LLM
  services yet - `agent`/`rag` were verified live and manually instead
  (see `.claude/rules/testing.md` for what's left to turn into committed,
  opt-in integration tests).

[Unreleased]: https://github.com/matanew1/ai-agent-platform/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/matanew1/ai-agent-platform/releases/tag/v0.1.0
