"""HTTP routes for cron schedules attached to owned agents.

Turn *execution* of a fired schedule happens in ``automation.runner``, not
here - this router only lets an authenticated user configure schedules for
their own agents, the same "configuration vs execution" split
``agent.controller``/``chat.controller`` already draw for definitions vs.
turns. Mounted from ``app/main.py``.
"""

from __future__ import annotations

from agent.service import AgentService
from authentication.controller import current_user
from fastapi import APIRouter, HTTPException, Request, status

from automation.schemas import CreateScheduleRequest, ScheduleResponse, UpdateScheduleRequest
from automation.service import InvalidCronExpressionError, ScheduleService
from shared.auth import AuthenticatedUser

router = APIRouter(prefix="/agents/{agent_id}/schedules", tags=["schedules"])


async def _require_owned_agent(request: Request, owner_id: str, agent_id: str) -> None:
    """Raise 404 unless ``agent_id`` belongs to ``owner_id`` - see agent.controller."""
    agent_service: AgentService = request.app.state.agent_service
    if await agent_service.get(owner_id, agent_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")


@router.post("", response_model=ScheduleResponse, status_code=status.HTTP_201_CREATED)
@current_user
async def create_schedule(
    agent_id: str,
    payload: CreateScheduleRequest,
    request: Request,
    current_user: AuthenticatedUser,
) -> ScheduleResponse:
    """Create a schedule for one agent owned by the authenticated user."""
    await _require_owned_agent(request, current_user.id, agent_id)
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
    await _require_owned_agent(request, current_user.id, agent_id)
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
    await _require_owned_agent(request, current_user.id, agent_id)
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
    """Update a schedule owned by the authenticated user."""
    await _require_owned_agent(request, current_user.id, agent_id)
    schedule_service: ScheduleService = request.app.state.schedule_service
    existing = await schedule_service.get(current_user.id, schedule_id)
    if existing is None or existing.agent_id != agent_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found.")
    try:
        schedule = await schedule_service.update(
            current_user.id, schedule_id, **payload.model_dump(exclude_unset=True)
        )
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
    await _require_owned_agent(request, current_user.id, agent_id)
    schedule_service: ScheduleService = request.app.state.schedule_service
    existing = await schedule_service.get(current_user.id, schedule_id)
    if existing is None or existing.agent_id != agent_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found.")
    await schedule_service.delete(current_user.id, schedule_id)
