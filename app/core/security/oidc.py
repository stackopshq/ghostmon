from functools import lru_cache

from authlib.integrations.starlette_client import OAuth, StarletteOAuth2App

from app.core.config import get_settings


class OIDCNotConfiguredError(RuntimeError):
    pass


class OIDCProvider:
    """OIDC SSO via authlib. Discovery, code exchange and ID-token validation
    (signature against the provider JWKS, plus state/nonce stored in the session)
    are handled by authlib; configure a real IdP through the OIDC_* env vars."""

    def __init__(self) -> None:
        settings = get_settings()
        self._enabled = settings.oidc_enabled
        self._oauth = OAuth()

        if self._enabled:
            if not (
                settings.oidc_issuer and settings.oidc_client_id and settings.oidc_client_secret
            ):
                raise OIDCNotConfiguredError(
                    "OIDC is enabled but issuer/client_id/client_secret are missing."
                )
            self._oauth.register(
                name="ghostmon_oidc",
                server_metadata_url=f"{settings.oidc_issuer.rstrip('/')}/.well-known/openid-configuration",
                client_id=settings.oidc_client_id,
                client_secret=settings.oidc_client_secret,
                client_kwargs={"scope": "openid email profile"},
            )

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def client(self) -> StarletteOAuth2App:
        if not self._enabled:
            raise OIDCNotConfiguredError("OIDC auth is disabled.")
        client: StarletteOAuth2App = self._oauth.ghostmon_oidc
        return client


@lru_cache
def get_oidc_provider() -> OIDCProvider:
    return OIDCProvider()
