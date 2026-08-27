"""Langue de l'interface, pour les pages rendues côté serveur.

GhostCal et GhostMail portent leurs traductions dans le navigateur : leur
interface est en React. GhostMon rend côté serveur, comme GhostLink — la même
idée atterrit donc ici sous la même forme : un dictionnaire par langue, un `t()`
exposé à tous les gabarits, et un choix qui survit dans un témoin.

TROIS DÉCISIONS, PARCE QUE LES TROIS SE PAIENT PLUS TARD
-------------------------------------------------------
**Les clés sont nommées par page** (`base.*`, `login.*`, `problems.*`), avec un
`common.*` pour ce qui revient partout. Un espace de noms plat invite un second
`title` qui veut dire autre chose ailleurs, et le jour où quelqu'un le réutilise
les deux pages divergent dans une seule langue.

**Une clé absente rend la clé elle-même**, assez visiblement pour qu'on la
remarque. La solution tentante — se replier sur l'anglais — cache l'oubli : la
page se lit encore, personne ne signale rien, et la moitié de l'interface reste
dans la mauvaise langue pendant des mois. `tests/test_i18n.py` refuse une
version où les deux dictionnaires ne portent pas exactement les mêmes clés ;
c'est le vrai garde-fou, ceci n'est que ce qui arrive si l'un passe quand même.

**Ce qui n'est PAS de la copie ne se traduit pas.** L'en-tête de chaque page
imite une invite de terminal (`~ $ ghostmon monitor list`) : c'est une commande,
pas une phrase. La traduire donnerait une commande fausse dans une interface qui
apprend à s'en servir. Le nom du produit et les valeurs d'état venues des
données (`ok`, `down`) restent également tels quels.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from starlette.requests import Request

COOKIE = "gm_lang"
DEFAULT = "en"

EN: dict[str, str] = {
    # --- Chrome : navigation et en-tête -------------------------------------
    "base.dashboard": "Dashboard",
    "base.hosts": "Hosts",
    "base.problems": "Problems",
    "base.discovery": "Discovery",
    "base.channels": "Channels",
    "base.escalation": "Escalation",
    "base.maintenances": "Maintenances",
    "base.settings": "Settings",
    "base.signOut": "Sign out",
    "base.toggleTheme": "Toggle theme",
    "base.toggleColorTheme": "Toggle color theme",
    "base.language": "Language",
    # --- Connexion -----------------------------------------------------------
    "login.title": "Sign in",
    "login.subtitle": "Access your GhostMonitor dashboard.",
    "login.email": "Email",
    "login.password": "Password",
    "login.submit": "Sign in",
    "login.or": "or",
    "login.sso": "Continue with SSO (OIDC)",
    "login.ssoDisabled": "OIDC is disabled",
    # --- Tableau de bord -----------------------------------------------------
    "dashboard.subtitle": "Real-time view of your monitors.",
    "dashboard.monitors": "Monitors",
    "dashboard.total": "total",
    "dashboard.newMonitor": "+ New monitor",
    "dashboard.maintenance": "maintenance",
    "dashboard.everySeconds": "every {n}s",
    "dashboard.empty": "No monitors yet",
    "dashboard.emptyHint": "Create your first monitor to start watching an endpoint.",
    # --- Problèmes -----------------------------------------------------------
    "problems.ongoing": "{n} ongoing",
    "problems.noneOngoing": "no ongoing problems",
    "problems.shown": "{n} shown",
    # --- Erreur --------------------------------------------------------------
    "error.backToDashboard": "Back to dashboard",
}

FR: dict[str, str] = {
    # --- Chrome : navigation et en-tête -------------------------------------
    "base.dashboard": "Tableau de bord",
    "base.hosts": "Hôtes",
    "base.problems": "Problèmes",
    "base.discovery": "Découverte",
    "base.channels": "Canaux",
    "base.escalation": "Escalade",
    "base.maintenances": "Maintenances",
    "base.settings": "Réglages",
    "base.signOut": "Se déconnecter",
    "base.toggleTheme": "Changer de thème",
    "base.toggleColorTheme": "Changer de couleur",
    "base.language": "Langue",
    # --- Connexion -----------------------------------------------------------
    "login.title": "Connexion",
    "login.subtitle": "Accédez à votre tableau de bord GhostMonitor.",
    "login.email": "Adresse e-mail",
    "login.password": "Mot de passe",
    "login.submit": "Se connecter",
    "login.or": "ou",
    "login.sso": "Continuer avec le SSO (OIDC)",
    "login.ssoDisabled": "Le SSO OIDC est désactivé",
    # --- Tableau de bord -----------------------------------------------------
    "dashboard.subtitle": "Vue en temps réel de vos sondes.",
    "dashboard.monitors": "Sondes",
    "dashboard.total": "au total",
    "dashboard.newMonitor": "+ Nouvelle sonde",
    "dashboard.maintenance": "maintenance",
    "dashboard.everySeconds": "toutes les {n} s",
    "dashboard.empty": "Aucune sonde pour l'instant",
    "dashboard.emptyHint": "Créez votre première sonde pour surveiller un point d'accès.",
    # --- Problèmes -----------------------------------------------------------
    "problems.ongoing": "{n} en cours",
    "problems.noneOngoing": "aucun problème en cours",
    "problems.shown": "{n} affiché(s)",
    # --- Erreur --------------------------------------------------------------
    "error.backToDashboard": "Retour au tableau de bord",
}

CATALOGUES: dict[str, dict[str, str]] = {"en": EN, "fr": FR}
LANGUES = tuple(CATALOGUES)


def resolve_locale(request: Request) -> str:
    """Le témoin gagne, puis la préférence du navigateur, puis l'anglais.

    Le témoin gagne à dessein : qui a choisi une langue l'a voulu, et un
    navigateur emprunté à un collègue ne doit pas le contredire en silence.
    """
    cookie = request.cookies.get(COOKIE)
    if cookie in CATALOGUES:
        return cookie
    header = request.headers.get("accept-language", "")
    for chunk in header.split(","):
        tag = chunk.split(";")[0].strip().lower()
        if tag[:2] in CATALOGUES:
            return tag[:2]
    return DEFAULT


def translator(locale: str) -> Callable[..., str]:
    catalogue = CATALOGUES.get(locale, EN)

    def t(key: str, **params: Any) -> str:
        # La clé elle-même, jamais un repli sur l'anglais : un repli se lit
        # bien, donc ne se signale pas. Voir la docstring du module.
        valeur = catalogue.get(key, key)
        return valeur.format(**params) if params else valeur

    return t


def context(request: Request) -> dict[str, Any]:
    """Processeur de contexte Jinja : chaque gabarit reçoit `t`, `locale`, `langues`."""
    locale = resolve_locale(request)
    return {"t": translator(locale), "locale": locale, "langues": LANGUES}
