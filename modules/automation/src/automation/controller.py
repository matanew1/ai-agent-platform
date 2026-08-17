"""HTTP routes for cron schedules attached to owned agents.

Turn *execution* of a fired schedule happens in ``automation.runner``, not
here - this router only lets an authenticated user configure schedules for
their own agents, the same "configuration vs execution" split
``agent.controller``/``chat.controller`` already draw for definitions vs.
turns. Mounted from ``app/main.py``.

Also validates a schedule's ``tools`` override is a subset of its agent's
own ``allowed_tools``, via ``shared.tools.require_tools_subset`` (shared
with ``chat.controller``'s identical check for an interactive turn's own
optional tool narrowing) - not ``ScheduleService``, which never loads an
``Agent`` at all (see its own docstring), and not ``automation.runner``
(which just uses whatever's already been validated and stored). This
router already loads the agent to check ownership on every route, so the
tools check rides along for free rather than adding a second agent lookup
somewhere else.
"""

from __future__ import annotations

from agent.service import AgentService
from authentication.controller import current_user
from fastapi import APIRouter, HTTPException, Request, status

from automation.schemas import CreateScheduleRequest, ScheduleResponse, UpdateScheduleRequest
from automation.service import InvalidCronExpressionError, ScheduleService
from shared.auth import AuthenticatedUser
from shared.tools import ToolsNotAllowedError, require_tools_subset
from shared.types import Agent

router = APIRouter(prefix="/agents/{agent_id}/schedules", tags=["schedules"])


async def _get_owned_agent(request: Request, owner_id: str, agent_id: str) -> Agent:
    """Return ``agent_id`` if it belongs to ``owner_id``, else raise 404."""
    agent_service: AgentService = request.app.state.agent_service
    agent = await agent_service.get(owner_id, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return agent


def _require_tools_subset(tools: list[str] | None, agent: Agent) -> None:
    """Map ``shared.tools``'s validation error onto this router's 422 convention."""
    try:
        require_tools_subset(tools, agent)
    except ToolsNotAllowedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.post("", response_model=ScheduleResponse, status_code=status.HTTP_201_CREATED)
@current_user
async def create_schedule(
    agent_id: str,
    payload: CreateScheduleRequest,
    request: Request,
    current_user: AuthenticatedUser,
) -> ScheduleResponse:
    """Create a schedule for one agent owned by the authenticated user."""
    agent = await _get_owned_agent(request, current_user.id, agent_id)
    _require_tools_subset(payload.tools, agent)
    schedule_service: ScheduleService = request.app.state.schedule_service
    try:
        schedule = await schedule_service.create(
            owner_id=current_user.id, agent_id=agent_id, **payload.model_dump()
        )
    except InvalidCronExpressionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return ScheduleResponse.model_validate(schedule, from_attributes=True)


@router.get("", response_model=list[ScheduleResponse])
@current_user
async def list_schedules(
    agent_id: str, request: Request, current_user: AuthenticatedUser
) -> list[ScheduleResponse]:
    """List schedules for one agent owned by the authenticated user."""
    await _get_owned_agent(request, current_user.id, agent_id)
    schedule_service: ScheduleService = request.app.state.schedule_service
    return [
        ScheduleResponse.model_validate(schedule, from_attributes=True)
        for schedule in await schedule_service.list_for_agent(current_user.id, agent_id)
    ]


@router.get("/{schedule_id}", response_model=ScheduleResponse)
@current_user
async def get_schedule(
    agent_id: str, schedule_id: str, request: Request, current_user: AuthenticatedUser
) -> ScheduleResponse:
    """Get one schedule owned by the authenticated user."""
    await _get_owned_agent(request, current_user.id, agent_id)
    schedule_service: ScheduleService = request.app.state.schedule_service
    schedule = await schedule_service.get(current_user.id, schedule_id)
    if schedule is None or schedule.agent_id != agent_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found.")
    return ScheduleResponse.model_validate(schedule, from_attributes=True)


@router.patch("/{schedule_id}", response_model=ScheduleResponse)
@current_user
async def update_schedule(
    agent_id: str,
    schedule_id: str,
    payload: UpdateScheduleRequest,
    request: Request,
    current_user: AuthenticatedUser,
) -> ScheduleResponse:
    """Update a schedule owned by the authenticated user.

    ``payload.agent_id``, if present and different from the URL's, moves
    the schedule to another agent the same caller owns - checked with the
    same ``_get_owned_agent`` 404 every other route uses, just against a
    second agent id. If the schedule's effective tools (whatever the
    payload sets, else its existing value) no longer fit the *target*
    agent's own ``allowed_tools``, they're reset to ``None`` rather than
    blocking the move outright - ``None`` always safely falls back to
    "whatever the new agent allows" (see ``automation.runner``), so a
    stale override never lingers silently invalid, and the caller can
    pick new tools in a follow-up edit instead of the move failing.
    """
    agent = await _get_owned_agent(request, current_user.id, agent_id)
    schedule_service: ScheduleService = request.app.state.schedule_service
    existing = await schedule_service.get(current_user.id, schedule_id)
    if existing is None or existing.agent_id != agent_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found.")

    changes = payload.model_dump(exclude_unset=True)
    target_agent = agent
    if "agent_id" in changes and changes["agent_id"] != agent_id:
        target_agent = await _get_owned_agent(request, current_user.id, changes["agent_id"])

    if "tools" in changes:
        _require_tools_subset(changes["tools"], target_agent)
    elif target_agent is not agent:
        try:
            require_tools_subset(existing.tools, target_agent)
        except ToolsNotAllowedError:
            changes["tools"] = None

    try:
        schedule = await schedule_service.update(current_user.id, schedule_id, **changes)
    except InvalidCronExpressionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if schedule is None:
        # Deleted between the existence check above and this write.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found.")
    return ScheduleResponse.model_validate(schedule, from_attributes=True)


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
@current_user
async def delete_schedule(
    agent_id: str, schedule_id: str, request: Request, current_user: AuthenticatedUser
) -> None:
    """Delete a schedule owned by the authenticated user."""
    await _get_owned_agent(request, current_user.id, agent_id)
    schedule_service: ScheduleService = request.app.state.schedule_service
    existing = await schedule_service.get(current_user.id, schedule_id)
    if existing is None or existing.agent_id != agent_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found.")
    await schedule_service.delete(current_user.id, schedule_id)
