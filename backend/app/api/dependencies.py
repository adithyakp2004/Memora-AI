from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import (
    AuthenticationConfigurationError,
    decode_access_token,
)
from app.db.database import get_db
from app.models.user import User

_bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()

    try:
        user_id: UUID = decode_access_token(credentials.credentials)
    except AuthenticationConfigurationError:
        raise HTTPException(
            status_code=503,
            detail="Authentication is not configured.",
        ) from None
    except (InvalidTokenError, ValueError, TypeError, KeyError):
        raise _unauthorized() from None

    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise _unauthorized()
    return user


def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_active:
        raise HTTPException(
            status_code=403,
            detail="This account is inactive.",
        )
    return current_user
