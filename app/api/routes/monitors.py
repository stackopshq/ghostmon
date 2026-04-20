from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DBSession
from app.core.schemas.monitor import MonitorRead
from app.core.services.monitor_service import MonitorService

router = APIRouter(prefix="/monitors", tags=["monitors"])


@router.get(
    "",
    response_model=list[MonitorRead],
    status_code=status.HTTP_200_OK,
    summary="List monitors for the authenticated user",
)
async def list_monitors(session: DBSession, current_user: CurrentUser) -> list[MonitorRead]:
    monitors = await MonitorService(session).list_for_owner(current_user.id)
    return [MonitorRead.model_validate(m) for m in monitors]
