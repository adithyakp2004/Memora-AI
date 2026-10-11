from collections.abc import Generator
from hashlib import sha256
import math
from secrets import token_urlsafe

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.db.database import get_db
from app.main import app
from app.services.embeddings import get_embedding_service


class TestEmbeddingService:
    @staticmethod
    def _vector(text: str) -> list[float]:
        values = [0.0] * 384
        for word in set(text.casefold().split()):
            digest = sha256(word.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % len(values)
            values[index] += 1.0 if digest[4] % 2 else -1.0
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, query: str) -> list[float]:
        return self._vector(query)


TEST_EMBEDDING_SERVICE = TestEmbeddingService()


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> Generator[TestClient, None, None]:
    monkeypatch.setattr(
        settings,
        "jwt_secret_key",
        SecretStr(token_urlsafe(48)),
    )
    monkeypatch.setattr(
        settings,
        "document_storage_dir",
        tmp_path / "documents",
    )

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    def override_get_db() -> Generator[Session, None, None]:
        with test_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_embedding_service] = (
        lambda: TEST_EMBEDDING_SERVICE
    )
    app.state.test_engine = engine
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        del app.state.test_engine
        Base.metadata.drop_all(engine)
        engine.dispose()
