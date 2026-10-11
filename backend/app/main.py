import logging

from fastapi.exceptions import RequestValidationError
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.routes.auth import router as auth_router
from app.api.routes.documents import router as documents_router
from app.api.routes.search import router as search_router
from app.core.config import settings
from app.db.database import (
    DatabaseNotConfiguredError,
    get_engine,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="MEMORA API",
    description="The API foundation for the MEMORA project.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=False,
    allow_methods=["DELETE", "GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(search_router)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    errors = []
    for error in exc.errors():
        location = error.get("loc", ())
        field = location[-1] if location else None
        if field == "email":
            message = "Enter a valid email address."
        elif field == "password":
            message = (
                "Password must be between 8 and 128 characters."
                if request.url.path.endswith("/register")
                else "Enter a password of at most 128 characters."
            )
        elif field == "full_name":
            message = "Enter a name of 1 to 120 characters."
        else:
            message = "Request validation failed."
        errors.append(
            {
                "loc": list(location),
                "msg": message,
                "type": error.get("type", "value_error"),
            }
        )

    return JSONResponse(status_code=422, content={"detail": errors})


@app.get("/api/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "message": "The MEMORA API is running.",
    }


@app.get("/api/health/db", tags=["health"])
def database_health_check() -> dict[str, str]:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except (DatabaseNotConfiguredError, SQLAlchemyError) as exc:
        logger.warning("Database health check failed (%s).", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unavailable",
                "message": "The database is not configured or is unavailable.",
            },
        ) from None

    return {
        "status": "ok",
        "message": "The MEMORA database is reachable.",
    }
