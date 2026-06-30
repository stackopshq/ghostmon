from fastapi import APIRouter

from app.api.routes.auth import router as auth_router
from app.api.routes.channels import router as channels_router
from app.api.routes.escalations import router as escalations_router
from app.api.routes.health import router as health_router
from app.api.routes.hosts import router as hosts_router
from app.api.routes.ingest import router as ingest_router
from app.api.routes.item_triggers import router as item_triggers_router
from app.api.routes.maintenances import router as maintenances_router
from app.api.routes.monitors import router as monitors_router
from app.api.routes.problems import router as problems_router
from app.api.routes.templates import router as templates_router
from app.api.routes.triggers import router as triggers_router

api_router = APIRouter(prefix="/api")
api_router.include_router(auth_router)
api_router.include_router(monitors_router)
api_router.include_router(triggers_router)
api_router.include_router(channels_router)
api_router.include_router(maintenances_router)
api_router.include_router(problems_router)
api_router.include_router(escalations_router)
api_router.include_router(hosts_router)
api_router.include_router(ingest_router)
api_router.include_router(item_triggers_router)
api_router.include_router(templates_router)

__all__ = ["api_router", "health_router"]
