from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.deps.db import DBSession
from app.api.routes.web._shared import login_redirect, resolve_current_user, templates
from app.core.services.maintenance_service import MaintenanceService
from app.core.services.monitor_service import MonitorService
from app.web.i18n import COOKIE, DEFAULT, LANGUES

router = APIRouter()


@router.get("/lang/{lang}", response_model=None)
async def set_language(lang: str, request: Request) -> RedirectResponse:
    """Poser la langue de l'interface, puis revenir d'où l'on vient.

    Le retour est contraint aux chemins internes : un `Referer` est fourni par
    le navigateur et un site tiers peut donc l'imposer. Renvoyer dessus ferait
    de ce lien une redirection ouverte, sur une route qui n'a aucune raison
    d'en être une.
    """
    if lang not in LANGUES:
        lang = DEFAULT
    referer = request.headers.get("referer", "")
    chemin = urlsplit(referer).path if referer else ""
    cible = chemin if chemin.startswith("/") and not chemin.startswith("//") else "/"
    reponse = RedirectResponse(cible, status_code=302)
    # Un an : c'est une préférence, pas une session. `httponly=False` à dessein —
    # rien ici n'est secret, et un sélecteur côté navigateur voudra la lire.
    reponse.set_cookie(COOKIE, lang, max_age=31_536_000, samesite="lax", httponly=False, path="/")
    return reponse


@router.get("/", response_class=HTMLResponse, response_model=None)
async def dashboard(request: Request, session: DBSession) -> HTMLResponse | RedirectResponse:
    user = await resolve_current_user(request, session)
    if user is None:
        return login_redirect()

    monitors = list(await MonitorService(session).list_for_owner(user.id))
    maintenance_svc = MaintenanceService(session)
    under_maintenance: set[str] = set()
    for monitor in monitors:
        if await maintenance_svc.is_monitor_under_maintenance(monitor.id):
            under_maintenance.add(str(monitor.id))

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        context={
            "current_user": user,
            "monitors": monitors,
            "under_maintenance": under_maintenance,
            "active_nav": "dashboard",
        },
    )
