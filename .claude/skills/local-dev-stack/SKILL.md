---
name: local-dev-stack
description: Bring up ai-agent-platform's local dev environment (docker-compose services, Ollama models, env, the app itself) and the common dev-loop commands
---

# Run ai-agent-platform locally

The full "how to run" is in [README.md](../../../README.md); this is the
checklist version plus the troubleshooting steps that come up most.

## First-time setup

1. **Start infrastructure:** `docker compose up -d` - brings up MongoDB
   (`:27017`), Redis (`:6379`), Qdrant (`:6333` API, `:6334` gRPC, dashboard
   at `:6333/dashboard`), plus two dev-only admin UIs: Mongo Express
   (`:8082`) and Redis Commander (`:8083`). None of the admin UIs are app
   runtime dependencies - only Mongo/Redis/Qdrant are.

2. **Pull local models** (only needed for `LLM_PROVIDER=ollama`, the
   default - skip if using `mistralai`):
   ```bash
   ollama pull qwen3:8b   # chat model, ~5.2GB
   ollama pull bge-m3     # embedding model, ~1.2GB
   ```
   See `.env.example`'s comments for why these two specifically (model-size
   vs. memory trade-offs measured on 16-17GB unified memory, and embedding
   context-window trade-offs) before swapping either.

3. **Env:** copy `.env.example` to `.env`, fill in real values. This step
   is not optional even for all-defaults local dev - `app/main.py` only
   reads `.env` if it exists (`load_dotenv`); without it every value
   silently falls back to code defaults, which is fine for infra hosts/ports
   but means `MISTRAL_API_KEY` etc. never gets picked up.

4. **Install the workspace:** `uv sync` (root + `agent`/`agents`/`rag`/`tool`
   workspace members - see the root `pyproject.toml`'s
   `[tool.uv.workspace]`).

5. **Run the app:** `uv run app` - starts uvicorn per `app/main.py:run()`,
   reads `APP_HOST`/`APP_PORT`/`APP_RELOAD` from env (defaults
   `0.0.0.0:8000`, reload on). Confirm with `curl localhost:8000/health`.

## Day-to-day dev loop

```bash
uv run pytest -q      # test suite
uv run ruff check .   # lint
uv run ruff format .  # format
```

Set `LOG_LEVEL=DEBUG` in `.env` for per-node LLM calls, tool calls, and
Redis/Mongo/Qdrant round trips - default is `INFO` and stays quiet on
purpose (see [architecture.md](../../rules/architecture.md#logging)'s level
discipline).

## Troubleshooting

- **Startup fails immediately with a Mongo/Redis connection error:**
  `MongoDatabase.connect()` pings Mongo at startup specifically so a bad
  URI or an unreachable instance fails loudly here instead of on the first
  `/agents` request - check `docker compose ps` and that `.env`'s
  `MONGODB_URI`/`REDIS_URL` match the compose ports above.
- **Chat/embedding calls fail with `LLMError`:** Ollama isn't running, or
  the configured model isn't pulled locally. `ollama list` to check what's
  actually pulled; the error message names the model and reason.
- **A chat turn silently reports "no tool results were available" even
  though a tool was clearly needed:** this was a real, previously-fixed bug
  - a reasoning model burning its whole token budget on chain-of-thought
  before any visible output. Confirm `OLLAMA_REASONING=false` is actually
  set (and that `.env` is being loaded at all - step 3 above).
- **Switched `OLLAMA_EMBEDDING_MODEL` and search/ingestion now errors:**
  expected - Qdrant's collection is created once with whatever vector
  dimensionality the first-ever embedding had, and a different embedding
  model almost always changes that dimensionality. Re-ingest everything, or
  point `QDRANT_COLLECTION` at a fresh collection name.
- **A new agent definition's first chat is noticeably slower than
  subsequent ones:** expected - `AgentRuntimeFactory` (`modules/agent/src/agent/runtime.py`)
  lazily compiles a runtime (including the LangGraph workflow) on first use
  per agent definition/version, then caches it for the process's lifetime.
