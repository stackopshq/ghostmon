from fastapi import APIRouter

from app.api.routes.web.auth import router as auth_router
from app.api.routes.web.channels import router as channels_router
from app.api.routes.web.dashboard import router as dashboard_router
from app.api.routes.web.escalation import router as escalation_router
from app.api.routes.web.hosts import router as hosts_router
from app.api.routes.web.maintenances import router as maintenances_router
from app.api.routes.web.monitors import router as monitors_router
from app.api.routes.web.problems import router as problems_router

router = APIRouter(tags=["web"], include_in_schema=False)
router.include_router(auth_router)
router.include_router(dashboard_router)
router.include_router(monitors_router)
router.include_router(hosts_router)
router.include_router(channels_router)
router.include_router(escalation_router)
router.include_router(maintenances_router)
router.include_router(problems_router)

__all__ = ["router"]
