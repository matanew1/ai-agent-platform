---
name: add-llm-provider
description: Add a new LLMProvider implementation (a third chat model alongside Ollama/Mistral) in infrastructure/llm.py
---

# Add a new LLM provider

For a third `LLM_PROVIDER` option alongside `ollama`/`mistralai` - a new
hosted or local chat model. `OllamaProvider`/`MistralProvider` in
`infrastructure/llm.py` are the two real implementations to copy the shape
of; this is the proof-by-example that `agent.ports.LLMProvider`
earns its keep as a real port, not a speculative one - see "Avoiding
over-engineering" in [architecture.md](../../rules/architecture.md).

## Steps

1. **Add a class to `infrastructure/llm.py`** implementing the same shape as
   the existing two - no inheritance needed, just matching methods
   (structural typing against `agent.ports.LLMProvider`):
   ```python
   async def generate(self, prompt: str, max_tokens: int | None = None) -> str: ...
   def generate_stream(self, prompt: str) -> AsyncIterator[str]: ...
   ```
   LangChain has a chat model for most hosted providers
   (`langchain-openai`, `langchain-anthropic`, ...) - wrap its
   `ainvoke`/`astream` the way `OllamaProvider`/`MistralProvider` wrap
   theirs, rather than hand-rolling HTTP calls.
   - If the model's LangChain integration builds its request options from
     its own pydantic fields (as both `ChatOllama` and `ChatMistralAI` do),
     set `max_tokens`/`num_predict` via `chat.model_copy(update={...})`,
     **not** `.bind()` - `.bind()` passes the kwarg straight through to the
     underlying SDK client call instead, which typically rejects an
     unrecognized kwarg outright. See `OllamaProvider.generate`'s comment
     for the full explanation if this needs re-deriving.
   - Route every returned completion through the existing `_require_content`
     helper before returning it - don't return `""` silently. This exists
     because of a real, previously-shipped bug: a reasoning-capable model
     spent its whole `max_tokens` budget on chain-of-thought, returned an
     empty completion, and the agent silently treated "no tool results were
     available" as a correct answer. `_require_content` turns that into a
     raised `LLMError` naming the provider's stop-reason field instead.
   - Also implement the module's own `rag.ports.LLMProvider` for
     free (RAG reranking) if it applies - that port only needs `generate`,
     a strict subset of the agent one, so no extra work is required for a
     provider that already satisfies the agent shape.

2. **Wire it into `_build_llm_provider()` in `app/lifespan.py`**, extending
   the `LLM_PROVIDER` branch. Fail fast at startup
   (`raise RuntimeError(...)`) if required config (an API key, a base URL)
   is missing - not on the first chat request. Follow the existing
   `mistralai` branch as the template.

3. **Log lengths, never content.** Every call site logs
   `prompt_len=%d`/`response_len=%d` via `len(...)`, never the actual
   prompt/response text - a prompt or response can carry sensitive user
   data. Match this exactly; don't add a debug log that prints the text
   "just for this one provider."

4. **Update `.env.example`** with the new provider's config block, in the
   same shape as the existing `# --- LLM provider ---` section - what
   `LLM_PROVIDER` value selects it, what env vars it needs, and (if you have
   real numbers) a one-line note on speed/cost/quality trade-offs the way
   the Ollama/Mistral entries already do. Don't assert free-tier or pricing
   claims you haven't actually verified against the provider's own current
   docs/console - a stale claim here is worse than no claim, since someone
   will configure against it.

5. **Tests.** LLM calls are always faked in unit tests
   (`FakeLLMProvider` in `tests/agent/test_agent.py` is the pattern) - don't
   add a test that makes a real call to the new provider in the default
   suite. A real call is only appropriate as a clearly-marked, opt-in
   manual/integration verification step (the same treatment
   `OllamaProvider`/`MistralProvider` themselves got - see
   [testing.md](../../rules/testing.md)), not part of `uv run pytest`.

6. **Verify:**
   ```bash
   uv run ruff format .
   uv run ruff check .
   uv run pytest -q
   ```
