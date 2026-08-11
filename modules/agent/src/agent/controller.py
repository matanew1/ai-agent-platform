"""HTTP routes for authenticated-user-scoped agents and their
persisted session history.

Streaming chat lives in ``chat.controller`` (turn *execution* is a
different concern from definition *configuration* and *persisted history*
here, even though both routers share the ``/agents`` prefix). Document
routes live in ``rag.controller`` and model-catalog routes live in
``model.controller`` - see each module's own docstring. Mounted from
``app/main.py``.
"""

from __future__ import annotations

from agent.schemas import AgentResponse, CreateAgentRequest, SessionResponse, UpdateAgentRequest
from agent.service import AgentService
from authentication.controller import CurrentUser
from fastapi import APIRouter, HTTPException, Request, status
from session.service import HybridSessionStore

router = APIRouter(prefix="/agents", tags=["agents"])


# --- Definition CRUD -------------------------------------------------------------


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: CreateAgentRequest, request: Request, current_user: CurrentUser
) -> AgentResponse:
    """Create an agent owned by the authenticated user."""
    definitions: AgentService = request.app.state.agent_service
    try:
        definition = await definitions.create(owner_id=current_user.id, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return AgentResponse.model_validate(definition, from_attributes=True)


@router.get("", response_model=list[AgentResponse])
async def list_agents(request: Request, current_user: CurrentUser) -> list[AgentResponse]:
    """List agents owned by the authenticated user."""
    definitions: AgentService = request.app.state.agent_service
    return [
        AgentResponse.model_validate(definition, from_attributes=True)
        for definition in await definitions.list(current_user.id)
    ]


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str, request: Request, current_user: CurrentUser) -> AgentResponse:
    """Get one agent owned by the authenticated user."""
    definitions: AgentService = request.app.state.agent_service
    definition = await definitions.get(current_user.id, agent_id)
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return AgentResponse.model_validate(definition, from_attributes=True)


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    payload: UpdateAgentRequest,
    request: Request,
    current_user: CurrentUser,
) -> AgentResponse:
    """Update an owned definition and advance its configuration version."""
    definitions: AgentService = request.app.state.agent_service
    try:
        definition = await definitions.update(
            current_user.id, agent_id, **payload.model_dump(exclude_unset=True)
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return AgentResponse.model_validate(definition, from_attributes=True)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: str, request: Request, current_user: CurrentUser) -> None:
    """Delete an agent belonging to the authenticated user."""
    definitions: AgentService = request.app.state.agent_service
    if not await definitions.delete(current_user.id, agent_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")


# --- Persisted sessions ---------------------------------------------------------


@router.get(
    "/{agent_id}/sessions",
    response_model=list[SessionResponse],
    response_model_exclude_defaults=True,
)
async def list_agent_sessions(
    agent_id: str, request: Request, current_user: CurrentUser
) -> list[SessionResponse]:
    """List retained sessions for one owned agent, newest first."""
    definitions: AgentService = request.app.state.agent_service
    if await definitions.get(current_user.id, agent_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    scoped_prefix = f"{current_user.id}:{agent_id}:"
    memory: HybridSessionStore = request.app.state.session_memory
    checkpoints = await memory.list_checkpoints(scoped_prefix)
    return [
        SessionResponse(
            session_id=checkpoint.session_id.removeprefix(scoped_prefix),
            history=checkpoint.history,
            updated_at=checkpoint.updated_at,
        )
        for checkpoint in checkpoints
        if checkpoint.session_id.startswith(scoped_prefix)
    ]


@router.get(
    "/{agent_id}/sessions/{session_id:path}",
    response_model=SessionResponse,
    response_model_exclude_defaults=True,
)
async def get_agent_session(
    agent_id: str,
    session_id: str,
    request: Request,
    current_user: CurrentUser,
) -> SessionResponse:
    """Fetch one retained session history for an owned agent."""
    definitions: AgentService = request.app.state.agent_service
    if await definitions.get(current_user.id, agent_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    scoped_prefix = f"{current_user.id}:{agent_id}:"
    scoped_id = f"{scoped_prefix}{session_id}"
    memory: HybridSessionStore = request.app.state.session_memory
    checkpoint = await memory.get_checkpoint(scoped_id)
    if checkpoint is None or checkpoint.session_id != scoped_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    return SessionResponse(
        session_id=checkpoint.session_id.removeprefix(scoped_prefix),
        history=checkpoint.history,
        updated_at=checkpoint.updated_at,
    )


@router.delete(
    "/{agent_id}/sessions/{session_id:path}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_agent_session(
    agent_id: str,
    session_id: str,
    request: Request,
    current_user: CurrentUser,
) -> None:
    """Delete one durable session belonging to an authenticated user's agent."""
    definitions: AgentService = request.app.state.agent_service
    if await definitions.get(current_user.id, agent_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    scoped_id = f"{current_user.id}:{agent_id}:{session_id}"
    memory: HybridSessionStore = request.app.state.session_memory
    if not await memory.delete_checkpoint(scoped_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
