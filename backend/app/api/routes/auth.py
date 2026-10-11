from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_active_user
from app.core.security import (
    AuthenticationConfigurationError,
    create_access_token,
    hash_password,
    verify_password,
    verify_unknown_user_password,
)
from app.db.database import get_db
from app.models.user import User
from app.schemas.auth import TokenResponse, UserCreate, UserLogin, UserRead

router = APIRouter(prefix="/api/auth", tags=["authentication"])


def _invalid_login() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password.",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
)
def register(
    payload: UserCreate,
    db: Session = Depends(get_db),
) -> UserRead:
    try:
        with db.begin():
            existing_user = db.scalar(
                select(User.id).where(User.email == str(payload.email))
            )
            if existing_user is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="An account with this email already exists.",
                )

            user = User(
                full_name=payload.full_name,
                email=str(payload.email),
                hashed_password=hash_password(payload.password),
            )
            db.add(user)
            db.flush()
            response = UserRead.model_validate(user)
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        ) from None

    return response


@router.post("/login", response_model=TokenResponse)
def login(
    payload: UserLogin,
    db: Session = Depends(get_db),
) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == str(payload.email)))
    if user is None:
        verify_unknown_user_password(payload.password)
        raise _invalid_login()

    if not verify_password(payload.password, user.hashed_password):
        raise _invalid_login()
    if not user.is_active:
        raise _invalid_login()

    try:
        token = create_access_token(user.id)
    except AuthenticationConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured.",
        ) from None

    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserRead)
def read_current_user(
    current_user: User = Depends(get_current_active_user),
) -> UserRead:
    return UserRead.model_validate(current_user)
