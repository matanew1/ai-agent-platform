"""LLM provider adapters.

``agent`` depends on the ``LLMProvider`` protocol defined in
``modules/agent/src/agent/internal/ports.py`` - it never imports this module. Each
class below only needs to structurally match that protocol's ``generate``/
``generate_stream`` signatures; the composition root (``app/lifespan.py``)
is what decides which provider gets wired into ``AgentService``, via the
``LLM_PROVIDER`` env var (``ollama`` or ``mistralai``).

Two providers are implemented, both via LangChain (this project already
depends on it for agent orchestration, so providers use it too rather than
hand-rolling HTTP calls): ``OllamaProvider`` (local, backed by
``ChatOllama``) and ``MistralProvider`` (remote, backed by
``ChatMistralAI`` - ``mistral-small-latest`` is free-tier eligible, see
``.env.example``). This second real implementation is what proves the
``LLMProvider`` port is actually load-bearing, not speculative - see
"Avoiding over-engineering" in ``.claude/rules/architecture.md``. To add a
third provider (OpenAI, Anthropic, ...), add a class with the same
signatures - LangChain has a chat model for most of them - and wire it
into ``_build_llm_provider`` in ``app/lifespan.py``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from langchain_mistralai import ChatMistralAI
from langchain_ollama import ChatOllama, OllamaEmbeddings

from shared.types import PlatformError

logger = logging.getLogger(__name__)


class LLMError(PlatformError):
    """Raised when an LLM call fails."""


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
            constructor argument here rather than part of the
            ``LLMProvider`` protocol every provider must implement.
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
        reasoning: bool | str | None = None,
        keep_alive: str | int | None = None,
    ) -> None:
        self._model = model
        chat_kwargs: dict[str, object] = {"base_url": base_url, "model": model}
        if reasoning is not None:
            chat_kwargs["reasoning"] = reasoning
        if keep_alive is not None:
            chat_kwargs["keep_alive"] = keep_alive
        self._chat = ChatOllama(**chat_kwargs)

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


class MistralProvider:
    """LLM provider backed by the remote Mistral AI API.

    Args:
        api_key: Mistral API key (see ``MISTRAL_API_KEY`` in ``.env.example``).
        model: Model name to use. ``mistral-small-latest`` (the default
            picked in ``app/lifespan.py``) is free-tier eligible - Mistral's
            free "Experiment" plan covers it, rate-limited rather than
            metered per token.
    """

    def __init__(self, api_key: str, model: str) -> None:
        self._model = model
        self._chat = ChatMistralAI(model=model, mistral_api_key=api_key)

    async def generate(self, prompt: str, max_tokens: int | None = None) -> str:
        """Generate a completion for a prompt.

        Args:
            prompt: Fully-rendered prompt text.
            max_tokens: Cap on generated tokens, for calls that only need a
                short, structured answer. ``None`` leaves it uncapped.

        Returns:
            The model's response text.

        Raises:
            LLMError: If the Mistral request fails (network, auth, rate
                limit, ...).
        """
        # Log lengths, not content - same policy as OllamaProvider above.
        logger.debug(
            "Mistral generate: model=%r prompt_len=%d max_tokens=%s",
            self._model,
            len(prompt),
            max_tokens,
        )
        # Same reasoning as OllamaProvider.generate: max_tokens has to be
        # set as a field (model_copy), not a .bind() kwarg, to actually
        # reach the request - see that method's comment for why.
        chat = (
            self._chat.model_copy(update={"max_tokens": max_tokens})
            if max_tokens is not None
            else self._chat
        )
        try:
            message = await chat.ainvoke(prompt)
        except Exception as exc:
            raise LLMError(f"Mistral request to {self._model!r} failed: {exc}") from exc

        content = message.content
        result = content if isinstance(content, str) else str(content)
        logger.debug("Mistral generate: model=%r response_len=%d", self._model, len(result))
        return _require_content(result, self._model, message.response_metadata.get("finish_reason"))

    async def generate_stream(self, prompt: str) -> AsyncIterator[str]:
        """Generate a completion for a prompt, yielding it token-by-token.

        Args:
            prompt: Fully-rendered prompt text.

        Yields:
            Successive text chunks that concatenate to the full response.

        Raises:
            LLMError: If the Mistral request fails, or the stream ends
                without a single chunk of visible content. Can surface after
                some chunks have already been yielded - see
                ``OllamaProvider.generate_stream``'s docstring, same caveat
                and same empty-stream handling.
        """
        logger.debug("Mistral generate_stream: model=%r prompt_len=%d", self._model, len(prompt))
        chunk_count = 0
        finish_reason: str | None = None
        try:
            async for chunk in self._chat.astream(prompt):
                finish_reason = chunk.response_metadata.get("finish_reason", finish_reason)
                content = chunk.content
                if not content:
                    continue
                chunk_count += 1
                yield content if isinstance(content, str) else str(content)
        except Exception as exc:
            raise LLMError(f"Mistral streaming request to {self._model!r} failed: {exc}") from exc
        logger.debug("Mistral generate_stream: model=%r chunks=%d", self._model, chunk_count)
        if chunk_count == 0:
            _require_content("", self._model, finish_reason)


class OllamaEmbedder:
    """Text embedder backed by a local Ollama embedding model."""

    def __init__(self, base_url: str, model: str) -> None:
        self._model = model
        self._embeddings = OllamaEmbeddings(base_url=base_url, model=model)

    async def embed(self, text: str) -> list[float]:
        """Create one embedding vector for text."""
        try:
            return await self._embeddings.aembed_query(text)
        except Exception as exc:
            raise LLMError(f"Ollama embedding request to {self._model!r} failed: {exc}") from exc
