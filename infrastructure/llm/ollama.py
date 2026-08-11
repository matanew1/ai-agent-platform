"""Ollama chat and embedding adapters."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from time import monotonic

from langchain_ollama import ChatOllama, OllamaEmbeddings
from ollama import AsyncClient

from infrastructure.errors import EmbeddingError, LLMError
from infrastructure.llm.protocol import EmbeddingClient, LanguageModelClient
from shared.implements import implements
from shared.types import ModelCatalogSnapshot

logger = logging.getLogger(__name__)

DEFAULT_TEMPERATURE = 0.3
_MODEL_CATALOG_TIMEOUT_SECONDS = 3.0
_MODEL_CATALOG_TTL_SECONDS = 30.0


def _require_content(text: str, model: str, done_reason: str | None = None) -> str:
    """Reject an empty completion instead of passing it off as an answer.

    A successful HTTP call that produced no visible text is a failure, not a
    result - neither caller (the agent's tool-call decision, its final
    answer) can do anything with ``""``, and returning it silently is how a
    real bug hid here: a reasoning-capable model (qwen3, gpt-oss,
    deepseek-r1, ...) with thinking enabled spends generated tokens on
    reasoning *before* any visible output, so a ``max_tokens`` cap meant for
    a short structured reply can be consumed entirely by that reasoning.
    Ollama then returns ``done_reason="length"`` with empty content, the
    tool-call step parses ``""`` into zero calls, and the agent confidently
    answers "no tool results were available" - no error anywhere.

    Args:
        text: The completion text as returned by the provider.
        model: Model name, for the error message.
        done_reason: Provider's stop reason, if it reports one.
            ``"length"`` means the token cap was hit.

    Returns:
        ``text`` unchanged, when it has content.

    Raises:
        LLMError: If ``text`` is empty or whitespace-only.
    """
    if text.strip():
        return text
    hint = (
        " - the max_tokens cap was consumed by the model's reasoning tokens before it "
        "produced any visible output; set OLLAMA_REASONING=false or raise the cap"
        if done_reason == "length"
        else ""
    )
    raise LLMError(f"{model!r} returned an empty completion (done_reason={done_reason!r}){hint}.")


def _looks_like_embedding_model(name: str, configured_embedding_model: str) -> bool:
    """Conservatively identify embedding-only models when capability data is absent."""
    normalized = name.casefold().removesuffix(":latest")
    configured = configured_embedding_model.casefold().removesuffix(":latest")
    if normalized == configured:
        return True
    embedding_markers = (
        "embed",
        "embedding",
        "all-minilm",
        "bge-",
        "bge_",
        "e5-",
        "gte-",
    )
    return any(marker in normalized for marker in embedding_markers)


def _supports_chat_model(
    name: str,
    configured_embedding_model: str,
    capabilities: list[str] | None,
) -> bool:
    """Interpret Ollama capability metadata with an older-server fallback."""
    normalized_capabilities = {capability.casefold() for capability in capabilities or []}
    if normalized_capabilities:
        return "completion" in normalized_capabilities
    return not _looks_like_embedding_model(name, configured_embedding_model)


@implements(LanguageModelClient)
class OllamaProvider:
    """LLM provider backed by a local Ollama server.

    Args:
        base_url: Ollama server URL (e.g. ``http://localhost:11434``).
        model: Model name to use (e.g. ``qwen3:8b``).
        reasoning: For reasoning-capable models (e.g. ``qwen3``, ``gpt-oss``),
            ``False`` disables chain-of-thought before the answer, a string
            like ``"low"`` reduces its effort, ``None`` (default) leaves the
            model's own default behavior alone. Applies to every call from
            this instance - see ``OLLAMA_REASONING`` in ``.env.example``.
            Reasoning effort isn't a concept every provider has, so it's a
            constructor argument here rather than part of the generic
            language-model contract.
        keep_alive: How long Ollama keeps this model loaded in memory after
            the last request, e.g. ``"30m"`` (duration string) or ``-1``
            (indefinitely). ``None`` leaves Ollama's own default (5m) alone.
            Ollama unloads a model's weights when this expires, so the next
            request pays the load cost again - this is purely about
            avoiding repeated model loads, unrelated to ``reasoning`` above.
            See ``OLLAMA_KEEP_ALIVE`` in ``.env.example``.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        temperature: float = DEFAULT_TEMPERATURE,
        reasoning: bool | str | None = None,
        keep_alive: str | int | None = None,
        embedding_model: str = "bge-m3",
    ) -> None:
        self.provider_name = "ollama"
        self.default_model = model
        self.default_temperature = temperature
        self._model = model
        self._base_url = base_url
        self._embedding_model = embedding_model
        self._catalog_snapshot: ModelCatalogSnapshot | None = None
        self._catalog_cached_at = 0.0
        self._catalog_lock = asyncio.Lock()
        chat_kwargs: dict[str, object] = {
            "base_url": base_url,
            "model": model,
            "temperature": temperature,
        }
        if reasoning is not None:
            chat_kwargs["reasoning"] = reasoning
        if keep_alive is not None:
            chat_kwargs["keep_alive"] = keep_alive
        self._chat = ChatOllama(**chat_kwargs)

    def with_options(
        self, *, model: str | None = None, temperature: float | None = None
    ) -> OllamaProvider:
        """Clone model settings while reusing LangChain's underlying clients."""
        if model is None and temperature is None:
            return self
        configured = object.__new__(type(self))
        configured.provider_name = self.provider_name
        configured.default_model = self.default_model
        configured.default_temperature = self.default_temperature
        configured._model = model or self._model
        configured._base_url = self._base_url
        configured._embedding_model = self._embedding_model
        configured._catalog_snapshot = self._catalog_snapshot
        configured._catalog_cached_at = self._catalog_cached_at
        configured._catalog_lock = self._catalog_lock
        updates: dict[str, object] = {}
        if model is not None:
            updates["model"] = model
        if temperature is not None:
            updates["temperature"] = temperature
        configured._chat = self._chat.model_copy(update=updates)
        return configured

    async def available_models(self) -> ModelCatalogSnapshot:
        """Discover installed Ollama chat models without making startup depend on Ollama.

        Ollama's ``/api/tags`` inventory establishes availability, while
        ``/api/show`` capability metadata distinguishes chat/completion
        models from embedding-only models. Older servers may omit that
        metadata, so the configured embedder and conservative name markers
        provide a fallback filter. A discovery outage returns the configured
        default as a non-authoritative snapshot; callers may still save it.
        """
        if (
            self._catalog_snapshot is not None
            and monotonic() - self._catalog_cached_at < _MODEL_CATALOG_TTL_SECONDS
        ):
            return self._catalog_snapshot

        async with self._catalog_lock:
            if (
                self._catalog_snapshot is not None
                and monotonic() - self._catalog_cached_at < _MODEL_CATALOG_TTL_SECONDS
            ):
                return self._catalog_snapshot
            snapshot = await self._discover_models()
            self._catalog_snapshot = snapshot
            self._catalog_cached_at = monotonic()
            return snapshot

    async def _discover_models(self) -> ModelCatalogSnapshot:
        try:
            async with AsyncClient(
                host=self._base_url, timeout=_MODEL_CATALOG_TIMEOUT_SECONDS
            ) as client:
                response = await client.list()
                model_names = sorted(
                    {item.model for item in response.models if item.model},
                    key=str.casefold,
                )
                chat_capabilities = await asyncio.gather(
                    *(self._supports_chat(client, model_name) for model_name in model_names)
                )
        except Exception as exc:
            logger.warning(
                "Ollama model discovery unavailable; using configured fallback: %s",
                exc,
            )
            return ModelCatalogSnapshot(models=(self.default_model,), authoritative=False)

        chat_models = tuple(
            model_name
            for model_name, supports_chat in zip(model_names, chat_capabilities, strict=True)
            if supports_chat
        )
        return ModelCatalogSnapshot(models=chat_models, authoritative=True)

    async def _supports_chat(self, client: AsyncClient, model_name: str) -> bool:
        try:
            details = await client.show(model_name)
        except Exception as exc:
            logger.debug(
                "Ollama capability lookup failed: model=%r error=%s",
                model_name,
                exc,
            )
            return not _looks_like_embedding_model(model_name, self._embedding_model)

        return _supports_chat_model(
            model_name,
            self._embedding_model,
            details.capabilities,
        )

    async def generate(self, prompt: str, max_tokens: int | None = None) -> str:
        """Generate a completion for a prompt.

        Args:
            prompt: Fully-rendered prompt text.
            max_tokens: Cap on generated tokens (``num_predict``), for
                calls that only need a short, structured answer. ``None``
                leaves it uncapped.

        Returns:
            The model's response text.

        Raises:
            LLMError: If the Ollama request fails, times out, the model
                isn't pulled locally, or it returns an empty completion -
                see ``_require_content``.
        """
        # Log lengths, not content - a prompt/response can carry sensitive
        # user data and doesn't belong in logs at any level.
        logger.debug(
            "Ollama generate: model=%r prompt_len=%d max_tokens=%s",
            self._model,
            len(prompt),
            max_tokens,
        )
        # ChatOllama builds its Ollama `options` payload from its own
        # num_predict *field* (see langchain_ollama's _chat_params), not
        # from arbitrary .bind() kwargs - those get passed straight through
        # to the underlying ollama.AsyncClient.chat() call instead, which
        # rejects an unrecognized num_predict kwarg outright. model_copy()
        # is a shallow pydantic copy - it reuses the same private
        # _async_client, it doesn't reconnect.
        chat = (
            self._chat.model_copy(update={"num_predict": max_tokens})
            if max_tokens is not None
            else self._chat
        )
        try:
            message = await chat.ainvoke(prompt)
        except Exception as exc:
            raise LLMError(f"Ollama request to {self._model!r} failed: {exc}") from exc

        content = message.content
        result = content if isinstance(content, str) else str(content)
        logger.debug("Ollama generate: model=%r response_len=%d", self._model, len(result))
        return _require_content(result, self._model, message.response_metadata.get("done_reason"))

    async def generate_stream(self, prompt: str) -> AsyncIterator[str]:
        """Generate a completion for a prompt, yielding it token-by-token.

        Args:
            prompt: Fully-rendered prompt text.

        Yields:
            Successive text chunks that concatenate to the full response.

        Raises:
            LLMError: If the Ollama request fails, times out, the model
                isn't pulled locally, or the stream ends without a single
                chunk of visible content (see ``_require_content``). Can
                surface after some chunks have already been yielded, if the
                connection drops mid-stream - the caller
                (``AgentService.run_stream``) has already sent those to the
                client and can only stop the stream there, not
                retroactively return a clean error response. The empty-stream
                case is not like that: nothing has been yielded yet, so it
                still reaches the client as a clean error.
        """
        logger.debug("Ollama generate_stream: model=%r prompt_len=%d", self._model, len(prompt))
        chunk_count = 0
        done_reason: str | None = None
        try:
            async for chunk in self._chat.astream(prompt):
                done_reason = chunk.response_metadata.get("done_reason", done_reason)
                content = chunk.content
                if not content:
                    continue
                chunk_count += 1
                yield content if isinstance(content, str) else str(content)
        except Exception as exc:
            raise LLMError(f"Ollama streaming request to {self._model!r} failed: {exc}") from exc
        logger.debug("Ollama generate_stream: model=%r chunks=%d", self._model, chunk_count)
        if chunk_count == 0:
            _require_content("", self._model, done_reason)


@implements(EmbeddingClient)
class OllamaEmbedder:
    """Create embeddings through the configured Ollama endpoint."""

    def __init__(self, base_url: str, model: str) -> None:
        self._model = model
        self._embeddings = OllamaEmbeddings(base_url=base_url, model=model)

    async def embed(self, text: str) -> list[float]:
        """Create one embedding vector for text."""
        try:
            return await self._embeddings.aembed_query(text)
        except Exception as exc:
            logger.warning("Embedding request failed: model=%r error=%s", self._model, exc)
            raise EmbeddingError(f"Embedding request for {self._model!r} failed: {exc}") from exc


__all__ = ["EmbeddingError", "LLMError", "OllamaEmbedder", "OllamaProvider"]
