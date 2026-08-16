"""HTTP contract tests for authenticated agent/document routes."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from agent.controller import router
from agent.service import AgentService
from authentication.repository import SESSION_COOKIE_NAME, SessionResult
from chat.controller import _stream_until_disconnect
from chat.controller import router as chat_router
from chat.service import ChatStreamMetadata
from fastapi import FastAPI
from fastapi.testclient import TestClient
from model.controller import router as models_router
from rag.controller import router as documents_router

from shared.auth import AuthenticatedUser, AuthenticationError
from shared.types import (
    Agent,
    ArtifactReference,
    ChatMessage,
    IndexedDocument,
    ModelCatalogSnapshot,
    SessionCheckpoint,
    ToolDefinition,
)


class _Repository:
    def __init__(self) -> None:
        self.items: dict[str, Agent] = {}

    async def create(self, definition: Agent) -> Agent:
        self.items[definition.id] = definition
        return definition

    async def get(self, owner_id: str, agent_id: str) -> Agent | None:
        item = self.items.get(agent_id)
        return item if item is not None and item.owner_id == owner_id else None

    async def list(self, owner_id: str) -> list[Agent]:
        return [item for item in self.items.values() if item.owner_id == owner_id]

    async def save(self, definition: Agent) -> bool:
        self.items[definition.id] = definition
        return True

    async def delete(self, owner_id: str, agent_id: str) -> bool:
        if await self.get(owner_id, agent_id) is None:
            return False
        del self.items[agent_id]
        return True


class _ToolService:
    def get_tools(self) -> list[ToolDefinition]:
        return [ToolDefinition(name="fetch", description="Fetches a URL.")]


class _DisconnectedRequest:
    def __init__(self) -> None:
        self._checks = 0

    async def is_disconnected(self) -> bool:
        self._checks += 1
        return self._checks > 1


class _ModelCatalog:
    provider_name = "ollama"
    default_model = "qwen3:8b"
    default_temperature = 0.3

    async def available_models(self) -> ModelCatalogSnapshot:
        return ModelCatalogSnapshot(
            models=("qwen3:8b", "qwen3:14b"),
            authoritative=True,
        )


class _DocumentIndex:
    """Fake satisfying rag.service.RAGService's document-library shape."""

    def __init__(self) -> None:
        self.ingested: list[dict[str, object]] = []
        self.documents: list[IndexedDocument] = []
        self.list_filters: list[dict[str, str]] = []
        self.deleted_filters: list[dict[str, str]] = []
        self.delete_result = False

    async def ingest_document(
        self,
        text: str,
        source_id: str,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        metadata: dict[str, str] | None = None,
    ) -> int:
        self.ingested.append({"text": text, "source_id": source_id, "metadata": metadata})
        return 1

    async def list_documents(self, metadata_filter: dict[str, str]) -> list[IndexedDocument]:
        self.list_filters.append(metadata_filter)
        return self.documents

    async def delete_document(self, metadata_filter: dict[str, str]) -> bool:
        self.deleted_filters.append(metadata_filter)
        return self.delete_result


class _Memory:
    """In-memory fake for persisted session reads."""

    def __init__(self) -> None:
        self.items: dict[str, SessionCheckpoint] = {}
        self.list_prefixes: list[str] = []

    async def get_checkpoint(self, session_id: str) -> SessionCheckpoint | None:
        return self.items.get(session_id)

    async def list_checkpoints(self, session_prefix: str) -> list[SessionCheckpoint]:
        self.list_prefixes.append(session_prefix)
        return sorted(
            (
                checkpoint
                for key, checkpoint in self.items.items()
                if key.startswith(session_prefix)
            ),
            key=lambda checkpoint: checkpoint.updated_at,
            reverse=True,
        )

    async def delete_checkpoint(self, session_id: str) -> bool:
        return self.items.pop(session_id, None) is not None


class _ChatService:
    """Fake satisfying the run_stream slice of chat.service.ChatService."""

    def __init__(self) -> None:
        self.received_attachments: list[tuple[str, str]] | None = None

    async def run_stream(
        self,
        session_id: str,
        message: str,
        tools: list[str] | None = None,
        attachments: list[tuple[str, str]] | None = None,
    ) -> tuple[ChatStreamMetadata, AsyncIterator[str]]:
        self.received_attachments = attachments

        async def _stream() -> AsyncIterator[str]:
            yield "ok"

        metadata = ChatStreamMetadata(
            tools_invoked=["generate_pdf"],
            chunks_retrieved=0,
            prep_time_seconds=0.0,
            artifacts=[
                ArtifactReference(
                    filename="profile.pdf",
                    download_url="/artifacts/profile.pdf",
                )
            ],
        )
        return metadata, _stream()


class _Authenticator:
    """Treat the test session-cookie value as the provider-issued subject."""

    async def authenticate_session(self, sealed_session: str | None) -> SessionResult:
        if sealed_session is None:
            raise AuthenticationError("No session cookie was provided.")
        return SessionResult(
            user=AuthenticatedUser(id=sealed_session), sealed_session=sealed_session
        )


class _ArtifactService:
    def __init__(self) -> None:
        self.grants: list[tuple[str, list[ArtifactReference]]] = []

    async def grant(self, user_id: str, artifacts: list[ArtifactReference]) -> None:
        self.grants.append((user_id, artifacts))

    async def can_download(self, user_id: str, filename: str) -> bool:
        return any(
            granted_user == user_id and any(item.filename == filename for item in artifacts)
            for granted_user, artifacts in self.grants
        )


def _client(*, authenticated: bool = True) -> tuple[TestClient, _DocumentIndex, _ChatService]:
    app = FastAPI()
    document_index = _DocumentIndex()
    chat_service = _ChatService()
    model_catalog = _ModelCatalog()
    app.state.agent_service = AgentService(
        _Repository(),
        _ToolService(),
        model_catalog,
    )
    app.state.rag_service = document_index
    app.state.session_memory = _Memory()
    app.state.tool_registry = _ToolService()
    app.state.model_catalog = model_catalog
    app.state.authenticator = _Authenticator()
    app.state.artifact_service = _ArtifactService()
    # chat.controller reads app.state.chat_service_factory (a real
    # app/lifespan.py builds chat.service.build_chat_service partially
    # applied over the shared dependencies) - faked here so route tests
    # don't compile a real LangGraph workflow, and scoped to this app
    # instance rather than mutating chat.controller globally.
    app.state.chat_service_factory = lambda agent: chat_service
    app.include_router(router)
    app.include_router(chat_router)
    app.include_router(documents_router)
    app.include_router(models_router)
    cookies = {SESSION_COOKIE_NAME: "owner-1"} if authenticated else None
    return TestClient(app, cookies=cookies), document_index, chat_service


def test_agent_routes_require_session_cookie_and_reject_caller_owner_id() -> None:
    unauthenticated_client, *_ = _client(authenticated=False)
    client, *_ = _client()

    missing_token = unauthenticated_client.get("/agents")
    caller_owned = client.post(
        "/agents",
        json={"owner_id": "attacker", "name": "Researcher", "allowed_tools": ["fetch"]},
    )
    created = client.post(
        "/agents",
        json={"name": "Researcher", "allowed_tools": ["fetch"]},
    )
    listed = client.get("/agents")
    another_users_list = client.get(
        "/agents",
        cookies={SESSION_COOKIE_NAME: "owner-2"},
    )

    assert missing_token.status_code == 401
    assert caller_owned.status_code == 422
    assert created.status_code == 201
    assert listed.status_code == 200
    assert [agent["name"] for agent in listed.json()] == ["Researcher"]
    assert another_users_list.json() == []


def test_openapi_has_session_cookie_security_and_no_public_owner_id_parameter() -> None:
    schema = _client()[0].app.openapi()

    create_schema = schema["components"]["schemas"]["CreateAgentRequest"]
    assert "owner_id" not in create_schema["properties"]
    assert schema["paths"]["/agents"]["get"]["security"] == [{"SessionCookie": []}]
    for path, methods in schema["paths"].items():
        if not (path.startswith("/agents") or path.startswith("/documents")):
            continue
        for operation in methods.values():
            if not isinstance(operation, dict):
                continue
            parameter_names = {parameter["name"] for parameter in operation.get("parameters", [])}
            assert "owner_id" not in parameter_names


def test_agent_generation_options_round_trip_and_validate() -> None:
    client, *_ = _client()

    created = client.post(
        "/agents",
        json={
            "name": "Researcher",
            "description": "Finds and cites reliable sources.",
            "allowed_tools": [],
            "model": "qwen3:14b",
            "temperature": 0.3,
        },
    )

    assert created.status_code == 201
    assert created.json()["description"] == "Finds and cites reliable sources."
    assert created.json()["model"] == "qwen3:14b"
    assert created.json()["temperature"] == 0.3

    agent_id = created.json()["id"]
    updated = client.patch(
        f"/agents/{agent_id}",
        json={"description": None, "model": None, "temperature": None},
    )
    invalid = client.patch(
        f"/agents/{agent_id}",
        json={"temperature": 2.1},
    )
    unavailable_model = client.patch(
        f"/agents/{agent_id}",
        json={"model": "embedding-only:latest"},
    )

    assert updated.status_code == 200
    assert updated.json()["description"] is None
    assert updated.json()["model"] is None
    assert updated.json()["temperature"] is None
    assert invalid.status_code == 422
    assert unavailable_model.status_code == 422
    assert "not an available ollama chat model" in unavailable_model.json()["detail"]


def test_model_catalog_exposes_frontend_configuration_contract() -> None:
    client, *_ = _client(authenticated=False)

    response = client.get("/models")

    assert response.status_code == 200
    assert response.json() == {
        "provider": "ollama",
        "default_model": "qwen3:8b",
        "models": [
            {"id": "qwen3:8b", "label": "qwen3:8b"},
            {"id": "qwen3:14b", "label": "qwen3:14b"},
        ],
        "temperature": {"min": 0.0, "max": 2.0, "step": 0.1, "default": 0.3},
    }


def test_documents_are_owner_scoped_not_nested_under_agents() -> None:
    """Documents belong to owner_id, not to one agent - see
    agent.controller's module docstring."""
    paths = _client()[0].app.openapi()["paths"]

    assert "/documents/text" in paths
    assert "/documents/file" in paths
    assert "/agents/{agent_id}/documents" not in paths
    assert "/agents/{agent_id}/documents/file" not in paths


def test_ingest_owner_document_scopes_by_owner_id_only() -> None:
    client, document_index, _ = _client()

    response = client.post(
        "/documents/text",
        json={"source_id": "notes", "text": "project notes"},
    )

    assert response.status_code == 200
    assert response.json() == {"source_id": "notes", "chunks_indexed": 1}
    assert document_index.ingested == [
        {"text": "project notes", "source_id": "owner-1:notes", "metadata": {"owner_id": "owner-1"}}
    ]


def test_list_and_delete_documents_use_exact_owner_source_filters() -> None:
    client, document_index, _ = _client()
    document_index.documents = [
        IndexedDocument(source_id="owner-1:report.pdf", chunks_indexed=3),
        # A malformed/legacy record that cannot be safely mapped back to a
        # client source id is not exposed.
        IndexedDocument(source_id="another-owner:secret.pdf", chunks_indexed=1),
    ]

    listed = client.get("/documents")
    missing = client.delete("/documents/report.pdf")
    document_index.delete_result = True
    deleted = client.delete("/documents/report.pdf")

    assert listed.status_code == 200
    assert listed.json() == [{"source_id": "report.pdf", "chunks_indexed": 3, "status": "indexed"}]
    assert document_index.list_filters == [{"owner_id": "owner-1"}]
    assert missing.status_code == 404
    assert deleted.status_code == 204
    assert document_index.deleted_filters == [
        {"owner_id": "owner-1", "source_id": "owner-1:report.pdf"},
        {"owner_id": "owner-1", "source_id": "owner-1:report.pdf"},
    ]


def test_session_routes_return_client_ids_and_history_with_owner_agent_isolation() -> None:
    client, *_ = _client()
    created = client.post(
        "/agents",
        json={"name": "Researcher", "allowed_tools": []},
    )
    agent_id = created.json()["id"]
    memory: _Memory = client.app.state.session_memory
    updated_at = datetime(2026, 8, 10, 12, 30, tzinfo=UTC)
    scoped_id = f"owner-1:{agent_id}:session/client-id"
    memory.items[scoped_id] = SessionCheckpoint(
        session_id=scoped_id,
        history=[
            ChatMessage(role="user", content="Compare the reports"),
            ChatMessage(
                role="assistant",
                content="Three gaps stand out.",
                tools_invoked=["extract_pdf"],
                chunks_retrieved=12,
                prep_time_seconds=0.24,
                artifacts=[
                    ArtifactReference(
                        filename="comparison.pdf",
                        download_url="/artifacts/comparison.pdf",
                    )
                ],
            ),
        ],
        updated_at=updated_at,
    )

    listed = client.get(f"/agents/{agent_id}/sessions")
    fetched = client.get(f"/agents/{agent_id}/sessions/session/client-id")
    wrong_owner = client.get(
        f"/agents/{agent_id}/sessions",
        cookies={SESSION_COOKIE_NAME: "owner-2"},
    )

    expected = {
        "session_id": "session/client-id",
        "history": [
            {"role": "user", "content": "Compare the reports"},
            {
                "role": "assistant",
                "content": "Three gaps stand out.",
                "tools_invoked": ["extract_pdf"],
                "chunks_retrieved": 12,
                "prep_time_seconds": 0.24,
                "artifacts": [
                    {
                        "filename": "comparison.pdf",
                        "download_url": "/artifacts/comparison.pdf",
                    }
                ],
            },
        ],
        "updated_at": "2026-08-10T12:30:00Z",
    }
    assert listed.status_code == 200
    assert listed.json() == [expected]
    assert fetched.status_code == 200
    assert fetched.json() == expected
    assert wrong_owner.status_code == 404
    assert memory.list_prefixes == [f"owner-1:{agent_id}:"]


def test_session_detail_rejects_a_mismatched_checkpoint_payload() -> None:
    client, *_ = _client()
    created = client.post(
        "/agents",
        json={"name": "Researcher", "allowed_tools": []},
    )
    agent_id = created.json()["id"]
    expected_key = f"owner-1:{agent_id}:session-1"
    memory: _Memory = client.app.state.session_memory
    memory.items[expected_key] = SessionCheckpoint(session_id="owner-2:other-agent:session-1")

    response = client.get(f"/agents/{agent_id}/sessions/session-1")

    assert response.status_code == 404


def test_delete_session_removes_only_the_authenticated_users_scoped_checkpoint() -> None:
    client, *_ = _client()
    created = client.post(
        "/agents",
        json={"name": "Researcher", "allowed_tools": []},
    )
    agent_id = created.json()["id"]
    memory: _Memory = client.app.state.session_memory
    scoped_id = f"owner-1:{agent_id}:session-1"
    memory.items[scoped_id] = SessionCheckpoint(session_id=scoped_id)

    deleted = client.delete(f"/agents/{agent_id}/sessions/session-1")
    missing = client.delete(f"/agents/{agent_id}/sessions/session-1")

    assert deleted.status_code == 204
    assert missing.status_code == 404
    assert scoped_id not in memory.items


def test_swagger_exposes_only_the_public_agents_surface() -> None:
    """Private workflow and retrieval routes are not mounted in the app."""
    from app.main import app

    schema = app.openapi()

    assert not any(path.startswith("/admin/") for path in schema["paths"])
    assert not any(tag["name"].startswith("[ADMIN ONLY]") for tag in schema.get("tags", []))
    assert "/models" in schema["paths"]
    assert "/agents/{agent_id}/chat" not in schema["paths"]
    assert "/agents/{agent_id}/chat/stream" in schema["paths"]
    assert schema["paths"]["/models"]["get"]["security"] == [{"SessionCookie": []}]
    assert schema["paths"]["/tools"]["get"]["security"] == [{"SessionCookie": []}]
    assert schema["paths"]["/tools/{name}"]["post"]["security"] == [{"SessionCookie": []}]


def test_chat_stream_indexes_attached_files_for_the_authenticated_user_and_agent() -> None:
    client, document_index, agent_service = _client()
    client.post(
        "/agents",
        json={"name": "Researcher", "allowed_tools": []},
    )
    agent_id = client.get("/agents").json()[0]["id"]
    file_content = base64.b64encode(b"attached plain text").decode()

    response = client.post(
        f"/agents/{agent_id}/chat/stream",
        json={
            "session_id": "s1",
            "message": "summarize this",
            "files": [{"filename": "notes.txt", "content_base64": file_content}],
        },
    )

    assert response.status_code == 200
    assert response.text == "ok"
    assert response.headers["X-Tools-Invoked"] == '["generate_pdf"]'
    assert response.headers["X-Artifacts"] == (
        '[{"filename": "profile.pdf", "download_url": "/artifacts/profile.pdf"}]'
    )
    artifact_service: _ArtifactService = client.app.state.artifact_service
    assert artifact_service.grants[0][0] == "owner-1"
    assert [artifact.filename for artifact in artifact_service.grants[0][1]] == ["profile.pdf"]
    assert agent_service.received_attachments == [("notes.txt", "attached plain text")]
    assert response.headers["X-Indexed-Documents"]
    assert document_index.ingested == [
        {
            "text": "attached plain text",
            "source_id": f"owner-1:chat/{agent_id}/90d2815c287c6e57-notes.txt",
            "metadata": {"owner_id": "owner-1", "agent_id": agent_id},
        }
    ]


def test_chat_stream_closes_the_provider_iterator_when_the_browser_disconnects() -> None:
    closed = False

    async def source() -> AsyncIterator[str]:
        nonlocal closed
        try:
            yield "first"
            yield "second"
        finally:
            closed = True

    async def collect() -> list[str]:
        return [chunk async for chunk in _stream_until_disconnect(_DisconnectedRequest(), source())]

    # The fake request reports "disconnected" starting on its second check, i.e.
    # after "first" has already been yielded, so the stream must stop there and
    # never reach "second" — proving the disconnect check, not stream exhaustion,
    # ended it.
    assert asyncio.run(collect()) == ["first"]
    assert closed is True


def test_chat_stream_rejects_invalid_base64_attachment() -> None:
    client, *_ = _client()
    client.post("/agents", json={"name": "R", "allowed_tools": []})
    agent_id = client.get("/agents").json()[0]["id"]

    response = client.post(
        f"/agents/{agent_id}/chat/stream",
        json={
            "session_id": "s1",
            "message": "hi",
            "files": [{"filename": "bad.txt", "content_base64": "not valid base64!!"}],
        },
    )

    assert response.status_code == 422
