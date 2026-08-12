"""Production adapters explicitly declare every Protocol they satisfy.

Only contracts with more than one real (or realistically near-term)
implementation are covered here - see CLAUDE.md's "Development Rules" and
``.claude/rules/architecture.md``'s "Avoiding over-engineering": a
single-implementation dependency (agent's repository/session-memory/model-
catalog, authentication, and artifact-access/content adapters, plus rag's
and tool's single concrete service) is typed against its concrete class
directly instead of a `Protocol` with exactly one satisfier.
"""

from __future__ import annotations

import pytest
from agent.repository import AgentRepository

from infrastructure.cache.protocol import Cache
from infrastructure.cache.redis import RedisCache
from infrastructure.database.postgres import PostgresDatabase
from infrastructure.database.protocol import Database
from infrastructure.llm.ollama import OllamaEmbedder, OllamaProvider
from infrastructure.llm.protocol import EmbeddingClient, LanguageModelClient
from infrastructure.vector_database.protocol import VectorDatabase
from infrastructure.vector_database.qdrant import QdrantVectorDatabase


@pytest.mark.parametrize(
    ("implementation", "contracts"),
    [
        (PostgresDatabase, (Database,)),
        (RedisCache, (Cache,)),
        (QdrantVectorDatabase, (VectorDatabase,)),
        (OllamaProvider, (LanguageModelClient,)),
        (OllamaEmbedder, (EmbeddingClient,)),
    ],
)
def test_production_adapter_declares_its_protocols(
    implementation: type, contracts: tuple[type, ...]
) -> None:
    assert implementation.__implemented_contracts__ == contracts


def test_agent_repository_has_no_protocol_marker() -> None:
    """AgentRepository is agent's only implementation - no Protocol to satisfy."""
    assert not hasattr(AgentRepository, "__implemented_contracts__")
