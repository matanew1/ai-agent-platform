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

from agent.draft_service import DraftService
from agent.schemas import (
    AgentResponse,
    CreateAgentRequest,
    RewriteDraftRequest,
    RewriteDraftResponse,
    SessionResponse,
    UpdateAgentRequest,
)
from agent.service import AgentService
from authentication.controller import current_user
from fastapi import APIRouter, HTTPException, Query, Request, status
from session.service import HybridSessionStore

from shared.auth import AuthenticatedUser
from shared.limits import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT
from shared.types import Page

router = APIRouter(prefix="/agents", tags=["agents"])


# --- Definition CRUD -------------------------------------------------------------


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
@current_user
async def create_agent(
    payload: CreateAgentRequest, request: Request, current_user: AuthenticatedUser
) -> AgentResponse:
    """Create an agent owned by the authenticated user."""
    agentService: AgentService = request.app.state.agent_service
    try:
        definition = await agentService.create(owner_id=current_user.id, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return AgentResponse.model_validate(definition, from_attributes=True)


@router.get("", response_model=list[AgentResponse])
@current_user
async def list_agents(request: Request, current_user: AuthenticatedUser) -> list[AgentResponse]:
    """List agents owned by the authenticated user."""
    agentService: AgentService = request.app.state.agent_service
    return [
        AgentResponse.model_validate(definition, from_attributes=True)
        for definition in await agentService.list(current_user.id)
    ]


@router.get("/{agent_id}", response_model=AgentResponse)
@current_user
async def get_agent(
    agent_id: str, request: Request, current_user: AuthenticatedUser
) -> AgentResponse:
    """Get one agent owned by the authenticated user."""
    agentService: AgentService = request.app.state.agent_service
    definition = await agentService.get(current_user.id, agent_id)
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return AgentResponse.model_validate(definition, from_attributes=True)


@router.patch("/{agent_id}", response_model=AgentResponse)
@current_user
async def update_agent(
    agent_id: str,
    payload: UpdateAgentRequest,
    request: Request,
    current_user: AuthenticatedUser,
) -> AgentResponse:
    """Update an owned definition and advance its configuration version."""
    agentService: AgentService = request.app.state.agent_service
    try:
        definition = await agentService.update(
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
@current_user
async def delete_agent(agent_id: str, request: Request, current_user: AuthenticatedUser) -> None:
    """Delete an agent belonging to the authenticated user."""
    agentService: AgentService = request.app.state.agent_service
    if not await agentService.delete(current_user.id, agent_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")


# --- Persisted sessions ---------------------------------------------------------


@router.get(
    "/{agent_id}/sessions",
    response_model=Page[SessionResponse],
    response_model_exclude_defaults=True,
)
@current_user
async def list_agent_sessions(
    agent_id: str,
    request: Request,
    current_user: AuthenticatedUser,
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    offset: int = Query(0, ge=0),
) -> Page[SessionResponse]:
    """List retained sessions for one owned agent, newest first, one page at a time."""
    agentService: AgentService = request.app.state.agent_service
    if await agentService.get(current_user.id, agent_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    scoped_prefix = f"{current_user.id}:{agent_id}:"
    memory: HybridSessionStore = request.app.state.session_memory
    checkpoints = await memory.list_checkpoints(scoped_prefix, limit=limit, offset=offset)
    total = await memory.count_checkpoints(scoped_prefix)
    return Page(
        items=[
            SessionResponse(
                session_id=checkpoint.session_id.removeprefix(scoped_prefix),
                history=checkpoint.history,
                updated_at=checkpoint.updated_at,
            )
            for checkpoint in checkpoints
            if checkpoint.session_id.startswith(scoped_prefix)
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{agent_id}/sessions/{session_id:path}",
    response_model=SessionResponse,
    response_model_exclude_defaults=True,
)
@current_user
async def get_agent_session(
    agent_id: str,
    session_id: str,
    request: Request,
    current_user: AuthenticatedUser,
) -> SessionResponse:
    """Fetch one retained session history for an owned agent."""
    agentService: AgentService = request.app.state.agent_service
    if await agentService.get(current_user.id, agent_id) is None:
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
@current_user
async def delete_agent_session(
    agent_id: str,
    session_id: str,
    request: Request,
    current_user: AuthenticatedUser,
) -> None:
    """Delete one durable session belonging to an authenticated user's agent."""
    agentService: AgentService = request.app.state.agent_service
    if await agentService.get(current_user.id, agent_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    scoped_id = f"{current_user.id}:{agent_id}:{session_id}"
    memory: HybridSessionStore = request.app.state.session_memory
    if not await memory.delete_checkpoint(scoped_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")


# --- Draft rewriting ---------------------------------------------------------------


@router.post("/{agent_id}/draft/rewrite", response_model=RewriteDraftResponse)
@current_user
async def rewrite_draft(
    agent_id: str,
    payload: RewriteDraftRequest,
    request: Request,
    current_user: AuthenticatedUser,
) -> RewriteDraftResponse:
    """Rewrite a user's draft chat message using one owned agent's own configuration.

    A single non-streamed LLM call, not a chat turn: nothing here is persisted to a
    session, and no tool actually runs - the agent's system prompt and allowed tools
    only frame how the draft gets rewritten. See ``agent.draft_service.DraftService``.
    """
    draft_service: DraftService = request.app.state.draft_service
    rewritten = await draft_service.rewrite(current_user.id, agent_id, payload.message)
    if rewritten is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return RewriteDraftResponse(message=rewritten)
