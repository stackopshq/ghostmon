"""Jetons d'accès signés — émission et vérification.

Sur `joserfc` et non `python-jose`. Le second tirait `ecdsa`, dont
PYSEC-2026-1325 n'a **aucune version corrigée** : la seule façon de fermer cet
avis était de retirer la dépendance, pas de l'ignorer. Le reste du dépôt était
déjà passé à `joserfc` ; ce fichier était le dernier appelant.

> **Le piège de la migration, et il est silencieux.** `python-jose` validait
> `exp` de lui-même à la lecture. `joserfc` ne valide **rien** par défaut :
> `jwt.decode()` vérifie la signature et rend les claims tels quels. Une
> traduction ligne à ligne aurait donc produit un service qui accepte
> indéfiniment des jetons expirés — sans erreur, sans journal, et sans qu'aucun
> test existant ne le remarque.
>
> D'où le `JWTClaimsRegistry` explicite ci-dessous, le même que celui de
> `resource_server.py`, et le test qui rejoue un jeton périmé.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import OctKey

from app.core.config import get_settings


class TokenError(Exception):
    pass


def _key() -> OctKey:
    return OctKey.import_key(get_settings().app_secret_key)


def create_access_token(
    subject: str | uuid.UUID,
    extra_claims: dict[str, Any] | None = None,
    expires_in: timedelta | None = None,
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    ttl = expires_in or timedelta(minutes=settings.jwt_access_ttl_minutes)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)
    encoded: str = jwt.encode({"alg": settings.jwt_algorithm}, payload, _key())
    return encoded


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        decoded = jwt.decode(token, _key(), algorithms=[settings.jwt_algorithm])
    except JoseError as exc:
        raise TokenError(str(exc)) from exc

    claims: dict[str, Any] = dict(decoded.claims)
    # `exp` en essential : un jeton SANS date d'expiration est refusé, pas
    # seulement un jeton périmé. Sans ce mot, un jeton forgé sans `exp`
    # passerait — la validation ne porterait que sur ce qui est présent.
    registry = jwt.JWTClaimsRegistry(exp={"essential": True})
    try:
        registry.validate(claims)
    except JoseError as exc:
        raise TokenError(str(exc)) from exc
    return claims
