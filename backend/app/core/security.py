from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from pwdlib import PasswordHash

from app.core.config import settings

JWT_ALGORITHM = "HS256"
MINIMUM_SECRET_BYTES = 32
_password_hash = PasswordHash.recommended()
_DUMMY_PASSWORD_HASH = _password_hash.hash("MEMORA-invalid-account-timing-check")


class AuthenticationConfigurationError(RuntimeError):
    pass

def _get_signing_secret() -> str:
    configured_secret = settings.jwt_secret_key
    if configured_secret is None:
        raise AuthenticationConfigurationError(
            "JWT_SECRET_KEY is not configured."
        )

    secret = configured_secret.get_secret_value()
    if (
        len(secret.encode("utf-8")) < MINIMUM_SECRET_BYTES
        or "replace" in secret.casefold()
        or "change_me" in secret.casefold()
        or secret == "GENERATE_A_LOCAL_SECRET_AT_LEAST_32_BYTES"
    ):
        raise AuthenticationConfigurationError(
            "JWT_SECRET_KEY must be a locally generated secret of at least 32 bytes."
        )

    return secret


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return _password_hash.verify(password, hashed_password)


def verify_unknown_user_password(password: str) -> None:
    _password_hash.verify(password, _DUMMY_PASSWORD_HASH)


def create_access_token(
    subject: UUID,
    expires_delta: timedelta | None = None,
) -> str:
    now = datetime.now(UTC)
    lifetime = (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.jwt_access_token_expire_minutes)
    )
    claims = {
        "sub": str(subject),
        "iat": now,
        "exp": now + lifetime,
    }
    return jwt.encode(claims, _get_signing_secret(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> UUID:
    claims = jwt.decode(
        token,
        _get_signing_secret(),
        algorithms=[JWT_ALGORITHM],
        options={"require": ["sub", "exp", "iat"]},
    )
    return UUID(claims["sub"])