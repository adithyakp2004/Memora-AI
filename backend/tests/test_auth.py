from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import create_access_token, verify_password
from app.main import app
from app.models.user import User
from app.schemas.auth import UserRead

REGISTER_PAYLOAD = {
    "full_name": "Mira Student",
    "email": "Mira.Student@Example.com",
    "password": "eight888",
}


def register(client, payload=None):
    return client.post("/api/auth/register", json=payload or REGISTER_PAYLOAD)


def test_successful_registration_returns_safe_profile(client):
    response = register(client)

    assert response.status_code == 201
    assert response.json()["email"] == "mira.student@example.com"
    assert set(response.json()) == {
        "id",
        "full_name",
        "email",
        "is_active",
        "created_at",
        "updated_at",
    }
    assert "password" not in response.text
    assert "hashed_password" not in response.text


def test_password_is_argon2_hashed_and_not_returned(client):
    response = register(client)
    user_id = response.json()["id"]

    with Session(app.state.test_engine) as db:
        user = db.scalar(select(User).where(User.id == UUID(user_id)))
        assert user is not None
        assert user.hashed_password != REGISTER_PAYLOAD["password"]
        assert user.hashed_password.startswith("$argon2id$")
        assert verify_password(REGISTER_PAYLOAD["password"], user.hashed_password)


def test_duplicate_email_is_rejected_case_insensitively(client):
    assert register(client).status_code == 201

    duplicate = dict(REGISTER_PAYLOAD, email="  MIRA.STUDENT@example.com ")
    response = register(client, duplicate)

    assert response.status_code == 409
    assert response.json()["detail"] == "An account with this email already exists."


def test_registration_rejects_short_password(client):
    response = register(client, dict(REGISTER_PAYLOAD, password="seven77"))

    assert response.status_code == 422
    assert all("input" not in error for error in response.json()["detail"])


def test_registration_accepts_exactly_eight_character_password(client):
    response = register(client, dict(REGISTER_PAYLOAD, password="eight888"))

    assert response.status_code == 201
    assert response.json()["email"] == "mira.student@example.com"


def test_validation_errors_do_not_echo_submitted_password(client):
    sensitive_value = "never-echo-this-password"
    response = register(
        client,
        dict(REGISTER_PAYLOAD, email="not-an-email", password=sensitive_value),
    )

    assert response.status_code == 422
    assert sensitive_value not in response.text


def test_successful_login_returns_bearer_token(client):
    register(client)

    response = client.post(
        "/api/auth/login",
        json={
            "email": "MIRA.STUDENT@example.com",
            "password": REGISTER_PAYLOAD["password"],
        },
    )

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]
    assert "password" not in response.text
    assert "hashed_password" not in response.text


def test_invalid_login_uses_generic_error(client):
    register(client)
    incorrect_password = client.post(
        "/api/auth/login",
        json={
            "email": REGISTER_PAYLOAD["email"],
            "password": "not-the-correct-password",
        },
    )
    unknown_email = client.post(
        "/api/auth/login",
        json={"email": "unknown@example.com", "password": "some-password"},
    )

    assert incorrect_password.status_code == unknown_email.status_code == 401
    assert incorrect_password.json() == unknown_email.json()
    assert incorrect_password.headers["www-authenticate"] == "Bearer"


def test_login_requires_a_configured_signing_key(client, monkeypatch):
    from app.core.config import settings

    register(client)
    monkeypatch.setattr(settings, "jwt_secret_key", None)
    response = client.post(
        "/api/auth/login",
        json={
            "email": REGISTER_PAYLOAD["email"],
            "password": REGISTER_PAYLOAD["password"],
        },
    )

    assert response.status_code == 503
    assert "secret" not in response.text.lower()


def test_login_rejects_the_environment_example_signing_placeholder(
    client, monkeypatch
):
    from pydantic import SecretStr

    from app.core.config import settings

    register(client)
    monkeypatch.setattr(
        settings,
        "jwt_secret_key",
        SecretStr("GENERATE_A_LOCAL_SECRET_AT_LEAST_32_BYTES"),
    )
    response = client.post(
        "/api/auth/login",
        json={
            "email": REGISTER_PAYLOAD["email"],
            "password": REGISTER_PAYLOAD["password"],
        },
    )

    assert response.status_code == 503
    assert "GENERATE_A_LOCAL_SECRET" not in response.text


def test_authenticated_user_can_read_safe_profile(client):
    registration = register(client)
    token = client.post(
        "/api/auth/login",
        json={
            "email": REGISTER_PAYLOAD["email"],
            "password": REGISTER_PAYLOAD["password"],
        },
    ).json()["access_token"]

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == registration.json()["id"]
    assert "hashed_password" not in response.json()
    assert "password" not in response.json()
    UserRead.model_validate(response.json())


def test_missing_bearer_token_is_rejected(client):
    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_invalid_bearer_token_is_rejected(client):
    response = client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer not-a-valid-token"},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_expired_bearer_token_is_rejected(client):
    register(client)
    with Session(app.state.test_engine) as db:
        user = db.scalar(select(User).where(User.email == "mira.student@example.com"))
        user_id = user.id
    expired_token = create_access_token(user_id, expires_delta=timedelta(seconds=-1))

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_inactive_user_cannot_access_protected_profile(client):
    register(client)
    with Session(app.state.test_engine) as db:
        user = db.scalar(select(User).where(User.email == "mira.student@example.com"))
        user.is_active = False
        user_id = user.id
        db.commit()

    token = create_access_token(user_id)
    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_general_health_does_not_depend_on_database(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_cors_is_limited_to_the_configured_local_frontend(client):
    from app.core.config import settings

    allowed = client.get(
        "/api/health",
        headers={"Origin": settings.frontend_origin},
    )
    rejected = client.get(
        "/api/health",
        headers={"Origin": "https://untrusted.example"},
    )

    assert allowed.headers["access-control-allow-origin"] == settings.frontend_origin
    assert "access-control-allow-origin" not in rejected.headers


def test_database_health_endpoint_executes_select_one(client, monkeypatch):
    from sqlalchemy import create_engine

    engine = create_engine("sqlite+pysqlite:///:memory:")
    monkeypatch.setattr("app.main.get_engine", lambda: engine)
    try:
        response = client.get("/api/health/db")
    finally:
        engine.dispose()

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_database_health_failure_is_sanitized_and_general_health_stays_healthy(
    client, monkeypatch
):
    from sqlalchemy.exc import OperationalError

    def fail_database_connection():
        raise OperationalError("connect", {}, Exception("private-connection-detail"))

    monkeypatch.setattr("app.main.get_engine", fail_database_connection)
    database_response = client.get("/api/health/db")
    api_response = client.get("/api/health")

    assert database_response.status_code == 503
    assert "private-connection-detail" not in database_response.text
    assert api_response.status_code == 200
