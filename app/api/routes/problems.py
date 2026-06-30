import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, DBSession
from app.core.schemas.problem_event import ProblemEventRead
from app.core.services.problem_event_service import ProblemEventService

router = APIRouter(prefix="/problems", tags=["problems"])


@router.get(
    "",
    response_model=list[ProblemEventRead],
    summary="List problem events (ongoing first, then recently resolved)",
)
async def list_problems(
    session: DBSession,
    current_user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[ProblemEventRead]:
    events = await ProblemEventService(session).list_for_owner(current_user.id, limit=limit)
    return [ProblemEventRead.model_validate(e) for e in events]


@router.post(
    "/{event_id}/ack",
    response_model=ProblemEventRead,
    summary="Acknowledge a problem event",
)
async def acknowledge_problem(
    event_id: uuid.UUID, session: DBSession, current_user: CurrentUser
) -> ProblemEventRead:
    event = await ProblemEventService(session).acknowledge(
        event_id, current_user.id, current_user.id, datetime.now(UTC)
    )
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Problem not found")
    return ProblemEventRead.model_validate(event)
