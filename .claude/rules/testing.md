# Testing

## Framework

- `pytest` + `pytest-asyncio` (`asyncio_mode = "auto"` so `async def test_...`
  just works — configure once in `pyproject.toml`, don't decorate every test).
- Run via `uv run pytest`. Never invoke `pytest` outside `uv run` — it must
  resolve against the project's locked environment.

## Layout

```
tests/
    agent/           — mirrors modules/agent/src/agent
    rag/             — mirrors modules/rag/src/rag
    tool/            — mirrors modules/tool/src/tool
    infrastructure/  — mirrors infrastructure/
```

Everything here today is a **unit test**: real dependencies (LLM, vector
store, tool registry, memory) are replaced with hand-written fakes
satisfying the module's `Protocol` ports — see `tests/agent/test_agent.py`
(`FakeLLMProvider` varies its response by prompt content, so the graph's
tool-calling branch gets exercised without a real LLM) and
`tests/rag/test_rag.py` for the pattern; `tests/tool/test_registry.py` for
a case with no external dependency at all (`ToolRegistry` is fully
in-process, so its tests assert real behavior); and
`tests/tool/test_tools.py` for real (not mocked) extraction against real
files - `extract_pdf`/`extract_markdown` have no network/DB dependency to
fake out, so there's no reason to.

There is no `tests/integration/` tree yet. `agent` and `rag` were instead
verified live and manually while implementing them (a real Ollama server
via `infrastructure.llm.{OllamaProvider,OllamaEmbedder}`, a real Qdrant
collection via `infrastructure.qdrant.QdrantVectorStore`, the full
`AgentService.run`/`RAGService.ingest_document`/`search` pipelines end to
end through the actual HTTP endpoints) rather than as a committed test - a
real next step here is turning those manual runs into proper opt-in
integration tests (mirroring the unit layout, or `test_*_integration.py`
alongside it, marked so `uv run pytest -m "not integration"` skips them by
default). `tool` has no external dependency to verify live against (see
[tool-conventions.md](tool-conventions.md#implementation-status)) - its
unit tests against real files are the whole story. Don't add the directory
speculatively before there's a real test to put in it.

## Unit vs integration

- **Unit tests** exercise one module's logic with every port (`VectorStore`,
  `Retriever`, `LLMProvider`, ...) replaced by a fake or mock that satisfies
  the `Protocol`. No network, no real DB, no real LLM call. These are the
  majority of the suite and must stay fast (milliseconds each).
- **Integration tests** exercise a real `infrastructure` adapter against a
  real backing service (containerized Mongo/Redis/Qdrant via
  `docker-compose.yml`), or exercise a full vertical slice through the
  FastAPI app with `httpx.AsyncClient`. Mock only the LLM/external network
  calls that would be slow, flaky, or costly — not the infrastructure under
  test.
- A module's service layer gets unit tests against fakes; its
  `infrastructure` adapter gets an integration test proving the adapter
  actually satisfies the port against the real system.
  `infrastructure/redis.py` and `infrastructure/llm.py` (both
  `OllamaProvider` and `OllamaEmbedder`) and `infrastructure/qdrant.py` are
  all implemented and verified (manually, see above) but still have no
  committed integration test - that gap, not a missing implementation, is
  what to fix first for all three. `tests/infrastructure/test_llm.py` is
  not that test and doesn't close the gap: it covers
  `infrastructure/llm.py`'s `_require_content` only, which is a pure
  function over text a provider already returned, so it needs neither a
  live model nor a mocked SDK internal. It exists as the regression test
  for a real bug (an empty completion being returned as if it were an
  answer, silently dropping every tool call) - the provider classes
  wrapped around it still need the live-service test described above.
  `database.py`'s CRUD methods
  (`find_one`/`insert_one`/`update_one`) are still `NotImplementedError`
  stubs (see the file's `TODO`s); there's nothing to test there yet -
  `connect`/`close` are real but have no dedicated test either, same gap
  as the other adapters.

## Mocking strategy

- Mock at the **port boundary** (the `Protocol` a module depends on), not
  three layers down inside a third-party client. If a test needs to mock
  `pymongo`/`motor` internals, that's a sign the code under test is reaching
  past its own `infrastructure` adapter.
- Prefer a small hand-written fake implementing the `Protocol` over
  `MagicMock` when the interface has more than one or two methods — a fake
  catches signature drift; a `MagicMock` doesn't.
- Don't mock what you don't own: wrap third-party SDKs in an `infrastructure`
  adapter first, then mock *that* adapter's interface in unit tests.
- LLM calls are mocked/stubbed in unit tests always (`FakeLLMProvider` in
  `tests/agent/test_agent.py`). Real LLM calls only happen in a clearly
  marked, opt-in integration test (slow, non-deterministic; local Ollama is
  free but still shouldn't run on every `uv run pytest`) — never in the
  default run.

## Expectations

- New business logic ships with unit tests in the same PR/change.
- A new `infrastructure` adapter ships with an integration test proving it
  satisfies its port.
- Bug fixes get a regression test that fails before the fix and passes after.
