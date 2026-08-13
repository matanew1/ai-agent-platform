# Python Style

## Formatting

- `ruff format` for formatting, `ruff check` for linting. Run via
  `uv run ruff format .` / `uv run ruff check .` — don't hand-format.
- Line length 100.
- One import per concept; group stdlib / third-party / local, no unused
  imports (ruff enforces this — don't suppress the rule).

## Naming

- `snake_case` for functions, variables, modules.
- `PascalCase` for classes, `Protocol`s, and Pydantic models.
- `UPPER_SNAKE_CASE` for module-level constants.
- Interfaces/ports read as nouns describing the capability (`VectorStore`,
  `ConversationRepository`), not `IVectorStore` or `VectorStoreBase`.
- No abbreviations that aren't obvious in context (`cfg` is fine, `mgr`/`svc`
  as a suffix on every class name is not).

## Typing

- Every function signature is fully typed: parameters and return type. No
  bare `def foo(x):`.
- Use built-in generics (`list[str]`, `dict[str, int]`, `X | None`) — this is
  a 3.12 codebase, don't import from `typing` for things the language now
  provides natively.
- `Any` is a last resort, only at genuine external boundaries (raw LLM
  response payloads, third-party SDK objects before they're mapped into a
  domain type). Never `Any` because a type was inconvenient to work out.
- Prefer `Protocol` for structural interfaces (see
  [architecture.md](architecture.md)); use `dataclass` or Pydantic models for
  data, not bare dicts, once a shape is used in more than one place.
- Run type checking as part of `/review`; don't let untyped code merge.

## Docstrings

Google style on every public function, class, and module:

```python
async def search(self, embedding: list[float], top_k: int = 5) -> list[Chunk]:
    """Find the most similar chunks to a query embedding.

    Args:
        embedding: Query vector, same dimensionality as the stored chunks.
        top_k: Maximum number of results to return.

    Returns:
        Chunks ordered by descending similarity.

    Raises:
        VectorStoreError: If the underlying store is unreachable.
    """
```

Private/internal helpers (`_leading_underscore`) don't need a docstring
unless the logic is non-obvious.

## Error handling

- No bare `except:`. Catch the specific exception you can handle.
- Define a small exception hierarchy per module that needs one (e.g.
  `RagError` → `EmbeddingError`, `VectorStoreError`) instead of raising raw
  `Exception` or leaking third-party exception types across a module
  boundary.
- Infrastructure adapters catch the underlying SDK/driver exceptions and
  re-raise a provider-neutral error — callers in `modules/*` never need to
  know whether PostgreSQL, Redis, Qdrant, or Ollama is underneath.
- Use structured logging (`logger.info("event", extra={...})`), never
  `print()`.
- Don't swallow exceptions to keep a request "succeeding" — surface failures;
  let the API layer translate them into the right HTTP response (see
  [api-conventions.md](api-conventions.md)).

## Async

- Anything doing I/O — DB calls, HTTP calls, LLM/embedding calls, tool
  calls — is `async def` and awaited. Use the available async client for
  network/database I/O (`asyncpg` through SQLAlchemy, `redis.asyncio`, async
  Qdrant, async LangChain); use `asyncio.to_thread` only for a genuinely
  synchronous library such as PDF/DOCX extraction.
- Don't mix sync blocking calls into async request handlers.
