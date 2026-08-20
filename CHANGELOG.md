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

### [1.0.2](https://github.com/matanew1/ai-agent-platform/compare/v1.0.1...v1.0.2) (2026-08-20)


### Fixed

* **graph:** match tool source, not just tool name, in _mentions_a_tool ([#31](https://github.com/matanew1/ai-agent-platform/issues/31)) ([e855d9e](https://github.com/matanew1/ai-agent-platform/commit/e855d9e0ddda8a8b78368b91ffbf2da5957ae853)), closes [#30](https://github.com/matanew1/ai-agent-platform/issues/30)

### [1.0.1](https://github.com/matanew1/ai-agent-platform/compare/v1.0.0...v1.0.1) (2026-08-20)


### Changed

* **graph:** narrow the tool-routing prompt for explicit/inbox requests ([#30](https://github.com/matanew1/ai-agent-platform/issues/30)) ([312d8c2](https://github.com/matanew1/ai-agent-platform/commit/312d8c2308440f675341a35aaeb90a2ae7231e84))

## [1.0.0](https://github.com/matanew1/ai-agent-platform/compare/v0.16.0...v1.0.0) (2026-08-20)


### Added


### [0.16.1](https://github.com/matanew1/ai-agent-platform/compare/v0.16.0...v0.16.1) (2026-08-20)

## [0.16.0](https://github.com/matanew1/ai-agent-platform/compare/v0.15.0...v0.16.0) (2026-08-20)


### Added

* **agent:** paginate session listing and add a draft-rewrite endpoint ([4df1ec9](https://github.com/matanew1/ai-agent-platform/commit/4df1ec9a0d3a8fd91eca145ed9c9e3e54e51565b))
* **app:** wire draft, account, and feedback services into the composition root ([df25940](https://github.com/matanew1/ai-agent-platform/commit/df25940c93389a3f684615c96d2344bb34315dd4))
* **authentication:** add a delete-account endpoint and AccountService ([f829de2](https://github.com/matanew1/ai-agent-platform/commit/f829de2e241b10adeccc9e6f37d27c44560695e9))
* **feedback:** add a feedback submission module ([9cc32a7](https://github.com/matanew1/ai-agent-platform/commit/9cc32a771af1d727d97f9831a68aef3a6b82884d))
* **rag:** paginate the document listing endpoint ([5414d27](https://github.com/matanew1/ai-agent-platform/commit/5414d27fc13fe73ec8f700438eeccf1bfba4dafe))
* **tool:** group MCP tools by source, add filesystem server, replace duckduckgo with tavily ([7b29151](https://github.com/matanew1/ai-agent-platform/commit/7b29151e5c039c055eaf1576513d500b35bb4395))

## [0.15.0](https://github.com/matanew1/ai-agent-platform/compare/v0.14.0...v0.15.0) (2026-08-17)


### Added

* **automation:** move a schedule to a different owned agent ([43eaef5](https://github.com/matanew1/ai-agent-platform/commit/43eaef534adbeffbfac25534cc4106472470dab7))

## [0.14.0](https://github.com/matanew1/ai-agent-platform/compare/v0.13.0...v0.14.0) (2026-08-17)


### Added

* **automation:** schedule title, description, and per-schedule tool scope ([873012e](https://github.com/matanew1/ai-agent-platform/commit/873012ee04e276b6069958c7e9d6d292ec8f3e93))


### Fixed

* **automation:** honor "empty allowed_tools = unrestricted" in tools checks ([7baaeb1](https://github.com/matanew1/ai-agent-platform/commit/7baaeb133c486e188c42027d103f7e8933b530c3))
* **graph:** distinguish "no tool restriction" from "restricted to zero tools" ([b11dc73](https://github.com/matanew1/ai-agent-platform/commit/b11dc73944c8609493fd85b46ebe1524afe79d18))

## [0.13.0](https://github.com/matanew1/ai-agent-platform/compare/v0.12.3...v0.13.0) (2026-08-16)


### Added

* **automation:** scheduled unattended agent runs ([036d9cf](https://github.com/matanew1/ai-agent-platform/commit/036d9cf42123ff149e7af155bd83c363cb6b5e4c))


### Fixed

* **automation:** address review findings ([b33ad94](https://github.com/matanew1/ai-agent-platform/commit/b33ad940e757ba68821f91ee173c5dc167111f8b))

### [0.12.3](https://github.com/matanew1/ai-agent-platform/compare/v0.12.2...v0.12.3) (2026-08-16)


### Fixed

* **security:** remove direct tool invocation and bound payload sizes ([8b87fe4](https://github.com/matanew1/ai-agent-platform/commit/8b87fe4ca1c0215357ebd4695955c58788da5f66))

### [0.12.2](https://github.com/matanew1/ai-agent-platform/compare/v0.12.1...v0.12.2) (2026-08-16)


### Changed

* **chat:** replace AgentRuntimeFactory with a plain per-turn builder ([8b1b2b9](https://github.com/matanew1/ai-agent-platform/commit/8b1b2b9c00339f972bd60c09acd4f4f3a371e890))

### [0.12.1](https://github.com/matanew1/ai-agent-platform/compare/v0.12.0...v0.12.1) (2026-08-16)


### Documentation

* **testing:** require browser E2E verification for frontend-facing changes ([3f58972](https://github.com/matanew1/ai-agent-platform/commit/3f58972958b4e9eefdf159c08bf35de4d58ad83a))


### Fixed

* **chat:** close provider stream when the browser disconnects ([d069e07](https://github.com/matanew1/ai-agent-platform/commit/d069e07431cd57d5cbbc0ef7fc5fd4108de703bc))

## [0.12.0](https://github.com/matanew1/ai-agent-platform/compare/v0.11.2...v0.12.0) (2026-08-13)


### Added

* **settings:** persist speech and accessibility preferences ([640e53c](https://github.com/matanew1/ai-agent-platform/commit/640e53c382f5b6f65a4b06b98e9624b1db0ab515))

### [0.11.2](https://github.com/matanew1/ai-agent-platform/compare/v0.11.1...v0.11.2) (2026-08-13)


### Added

* **settings:** add durable workspace settings ([e8e1074](https://github.com/matanew1/ai-agent-platform/commit/e8e1074adf0d0825156da0340177134e4d692149))

### [0.11.1](https://github.com/matanew1/ai-agent-platform/compare/v0.11.0...v0.11.1) (2026-08-13)


### Fixed

* **agent:** prioritize enabled tools in routing ([27db291](https://github.com/matanew1/ai-agent-platform/commit/27db291a3dbfa10d4ad1a8a66aed689634a8c033))

## [0.11.0](https://github.com/matanew1/ai-agent-platform/compare/v0.10.0...v0.11.0) (2026-08-13)


### Fixed

* **authentication:** require current user on protected routes ([4c451eb](https://github.com/matanew1/ai-agent-platform/commit/4c451ebc292fdfd356a48f7c84864e773989b693))


### Added

* **chat:** expose retrieved sources and strengthen tool use ([5ddfef3](https://github.com/matanew1/ai-agent-platform/commit/5ddfef3511d91f06761d03c00e3094e01586e553))

## [0.10.0](https://github.com/matanew1/ai-agent-platform/compare/v0.9.0...v0.10.0) (2026-08-13)


### Fixed

* **chat:** stop the model from hallucinating stale download links ([#15](https://github.com/matanew1/ai-agent-platform/issues/15)) ([d87f7ae](https://github.com/matanew1/ai-agent-platform/commit/d87f7aed07a8f2387f74eb6409c73ff287e2850b))


### Added

* **chat:** persist chat attachments in RAG ([2f00404](https://github.com/matanew1/ai-agent-platform/commit/2f004048e0e5e2cd4d4fec6058ece96046bac24c))


### Documentation

* **dev:** document Redis Commander ([d35b567](https://github.com/matanew1/ai-agent-platform/commit/d35b567702330632929e817847d05d53cd104709))

## [0.9.0](https://github.com/matanew1/ai-agent-platform/compare/v0.8.0...v0.9.0) (2026-08-12)


### Added

* **tool:** render Markdown when generating PDFs instead of raw text ([7eafcae](https://github.com/matanew1/ai-agent-platform/commit/7eafcae9f648e9e6df8392c3ad77512de8d122aa))


### Fixed

* **tool:** tighten PDF Markdown rendering per review ([04b0ed3](https://github.com/matanew1/ai-agent-platform/commit/04b0ed3ecf56f4e17b6562a98d8088baff630e03)), closes [#14](https://github.com/matanew1/ai-agent-platform/issues/14)

## [0.8.0](https://github.com/matanew1/ai-agent-platform/compare/v0.7.2...v0.8.0) (2026-08-12)


### Added

* **tool:** add analyze_ats_compatibility, a local ATS resume-parsing tool ([9861d8f](https://github.com/matanew1/ai-agent-platform/commit/9861d8f78cac267b66a885bbae6158ac46dc5765))

### [0.7.2](https://github.com/matanew1/ai-agent-platform/compare/v0.7.1...v0.7.2) (2026-08-12)


### Fixed

* add the missing initial Alembic migration ([fb0367b](https://github.com/matanew1/ai-agent-platform/commit/fb0367b356991d0e81ca7c681009c2369789acaa)), closes [#8](https://github.com/matanew1/ai-agent-platform/issues/8)

### [0.7.1](https://github.com/matanew1/ai-agent-platform/compare/v0.7.0...v0.7.1) (2026-08-12)


### Documentation

* **authentication:** add dev/prod env templates and auto-selecting env loading ([93e0553](https://github.com/matanew1/ai-agent-platform/commit/93e0553bf941466e66e6d42e19f5265c86611318))


### Fixed

* load .env before templates so local overrides actually take effect ([3d067d9](https://github.com/matanew1/ai-agent-platform/commit/3d067d9057e622d378ed29f82ca731b3dbf30bf4))

## [0.7.0](https://github.com/matanew1/ai-agent-platform/compare/v0.6.0...v0.7.0) (2026-08-12)


### Changed

* **infrastructure:** migrate persistence to PostgreSQL, reorganize capability adapters ([bf430da](https://github.com/matanew1/ai-agent-platform/commit/bf430da82678d3df713024d93d145b4076610ce4))
* **modules:** split agent into agent/chat/graph/session, extract artifact/authentication/model ([21df40a](https://github.com/matanew1/ai-agent-platform/commit/21df40a1f3b1e2d32581ce3be8224a29e9d37319))


### Added

* **app:** wire the WorkOS session-cookie authenticator into the composition root ([d97a4de](https://github.com/matanew1/ai-agent-platform/commit/d97a4de10df0cc08c0bdf42bcef3a15dbfb88d86))
* **authentication:** add /auth/login, /auth/callback, /auth/logout, /auth/me routes ([a86bd1a](https://github.com/matanew1/ai-agent-platform/commit/a86bd1aa91c4aafbb6a1c1c570dcf2d7311b3d3b))
* **authentication:** implement WorkOS AuthKit vanilla session-cookie flow ([a4f4252](https://github.com/matanew1/ai-agent-platform/commit/a4f4252639df8793f013d2ca6213a575cb6f06ee))


### Fixed

* **authentication:** handle JWKS outages and empty user ids, dedupe callback error redirect ([4557e39](https://github.com/matanew1/ai-agent-platform/commit/4557e39d3c6080737aea02c94a13756525ed2710))
* watch chat/graph/session for reload, dispose Postgres engine on failed connect ([c838b7f](https://github.com/matanew1/ai-agent-platform/commit/c838b7f6247c558be5074ae5184be1908c78a0c4))

## [0.6.0](https://github.com/matanew1/ai-agent-platform/compare/v0.5.1...v0.6.0) (2026-08-11)


### Changed

* **agent:** merge agent+agents into one module, flatten internal/ repo-wide ([883ad44](https://github.com/matanew1/ai-agent-platform/commit/883ad44cb9669d3d07c458b9efff2a7ef41a3bc7))
* isolate public agents module ([93bc44b](https://github.com/matanew1/ai-agent-platform/commit/93bc44b586d6c8db95b4e9b7142e21993aa04840))
* make agents the only public API ([7278547](https://github.com/matanew1/ai-agent-platform/commit/72785476abe5335e60585881109b77c91346c35e))
* remove private admin API routes ([c20ca58](https://github.com/matanew1/ai-agent-platform/commit/c20ca584cfdb47397653a30b08ea54e16ea9986c))


### Documentation

* **env:** document APP_CORS_ORIGINS in .env.example ([5581a1f](https://github.com/matanew1/ai-agent-platform/commit/5581a1ff6f9224536a025343a69824252428fe61))
* refresh CLAUDE.md, README, and rule docs for the merged agent module ([4ee847b](https://github.com/matanew1/ai-agent-platform/commit/4ee847b3a9b0c163c34ce3e8e0863d0c6e4d3661))


### Added

* add configurable agent definitions ([4e9c29b](https://github.com/matanew1/ai-agent-platform/commit/4e9c29b08600b888a9820603b7fe317e47b5b7fb))
* **agent:** track artifacts generated during a turn, guard tool routes ([09f21ff](https://github.com/matanew1/ai-agent-platform/commit/09f21ff9cd02774855edc0b29b88ad834e33c742))
* **app:** add CORS middleware for cross-origin API access ([f2d7ff1](https://github.com/matanew1/ai-agent-platform/commit/f2d7ff131689acd00c8f5f48044b23ab36cb3bbf))
* **app:** bearer-JWT authentication, model selection, sessions, and generated-file artifacts ([e05b597](https://github.com/matanew1/ai-agent-platform/commit/e05b59715bcefa6cecbae59dac79f59205e1655d))
* label private APIs in swagger ([f762c16](https://github.com/matanew1/ai-agent-platform/commit/f762c16d98cba6b5c56e4aa30f5dfbdb182e5cda))


### Fixed

* **app:** require ownership to download generated artifacts ([ef17d25](https://github.com/matanew1/ai-agent-platform/commit/ef17d2553556532dfcbf4f860e110e798e5dd335))
* **infrastructure:** tolerate a session-cache outage without losing history ([5ae22f2](https://github.com/matanew1/ai-agent-platform/commit/5ae22f25b5b2fa7edc233607e71b0e8250157756))
* keep fetch mcp stdout protocol clean ([0437ac4](https://github.com/matanew1/ai-agent-platform/commit/0437ac437ee44f917517ab65a157b4763dc5a0d8))

### [0.5.1](https://github.com/matanew1/ai-agent-platform/compare/v0.5.0...v0.5.1) (2026-08-08)


### Added

* **registry:** enable fluent chaining for local and MCP tool registrations ([401f80d](https://github.com/matanew1/ai-agent-platform/commit/401f80d95db5c7084bd0c464cdfaf4d23d227217))

## [0.5.0](https://github.com/matanew1/ai-agent-platform/compare/v0.4.0...v0.5.0) (2026-08-08)


### Added

* **agent:** let /chat restrict which tools the agent may use ([bc5d851](https://github.com/matanew1/ai-agent-platform/commit/bc5d851010084c160d60a3285540b3080db51e39))
* **tool:** enable the duckduckgo MCP server for web search ([511a9c1](https://github.com/matanew1/ai-agent-platform/commit/511a9c1652c1cae569e3d1f628aa12e7d0a4fbcc))

## [0.4.0](https://github.com/matanew1/ai-agent-platform/compare/v0.3.0...v0.4.0) (2026-08-08)


### Added

* **agent:** report execution time, tools invoked, and chunks retrieved ([e73748c](https://github.com/matanew1/ai-agent-platform/commit/e73748cace7ee854ef62d3735e2b2babc7a51247))
* **rag:** add LLM-based reranking with a per-call toggle ([2095c88](https://github.com/matanew1/ai-agent-platform/commit/2095c881eba638a7f8998e984f267ea815e66196))


### Fixed

* **rag:** scale reranking's max_tokens with candidate count ([638a14d](https://github.com/matanew1/ai-agent-platform/commit/638a14d0dcbf0e8589a7c60bac77de2b217351dd))

## [0.3.0](https://github.com/matanew1/ai-agent-platform/compare/v0.2.0...v0.3.0) (2026-08-08)


### Fixed

* **rag:** make chunk_text honest about overlap, fences, and tiny chunks ([391c1e2](https://github.com/matanew1/ai-agent-platform/commit/391c1e27ef00fae907d51c1ce942a6b04e33c85e))


### Documentation

* **tool:** record get_current_time's bare-phrasing selection limit ([9381346](https://github.com/matanew1/ai-agent-platform/commit/9381346a8c6a85853855bb57fda5feeeb9822307))


### Added

* **logging:** colorize dev logs and validate LOG_LEVEL/LOG_COLOR ([a3d4170](https://github.com/matanew1/ai-agent-platform/commit/a3d4170a739efdf6d0d93e62111c72df4c00fa3f))

## [0.2.0](https://github.com/matanew1/ai-agent-platform/compare/v0.1.0...v0.2.0) (2026-08-07)


### Added

* **tool:** add MCP server support with fetch and time servers ([6b4de24](https://github.com/matanew1/ai-agent-platform/commit/6b4de2455107cd72a1ab4899577b926d7dcf7a73))


### Fixed

* **llm:** raise on an empty completion instead of returning it as an answer ([4d79083](https://github.com/matanew1/ai-agent-platform/commit/4d79083167cb6b9cf70a33c324847e4852b83758))

## [0.1.0] - 2026-08-07

Initial tracked release - `agent`, `rag`, and `tool` are all fully
implemented and verified against live services (real Ollama, real
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
- Ollama chat and embedding adapters (`qwen3:8b` is the default chat model).
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
