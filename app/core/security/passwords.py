from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import get_settings


def _build_hasher() -> PasswordHasher:
    settings = get_settings()
    return PasswordHasher(
        time_cost=settings.argon2_time_cost,
        memory_cost=settings.argon2_memory_cost,
        parallelism=settings.argon2_parallelism,
    )


_hasher = _build_hasher()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except VerifyMismatchError:
        return False


# A throwaway hash so a login attempt costs the same whether or not the account
# exists — removes the user-enumeration timing oracle.
_DUMMY_HASH = _hasher.hash("ghostmon-timing-equalizer")


def dummy_verify(plain: str) -> None:
    """Run a hash verification against a constant hash (always fails) to equalise
    timing when there is no real password hash to check."""
    try:
        _hasher.verify(_DUMMY_HASH, plain)
    except VerifyMismatchError:
        pass
