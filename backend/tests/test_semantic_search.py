import logging
import math
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import event, func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, settings
from app.db.database import get_engine
from app.main import app
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.services.embeddings import EmbeddingError, get_embedding_service

PASSWORD = "document-password-123"


class ControlledEmbeddingService:
    def __init__(
        self,
        vectors_by_text: dict[str, list[float]],
        query_vector: list[float],
    ) -> None:
        self.vectors_by_text = vectors_by_text
        self.query_vector = query_vector

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.vectors_by_text[text] for text in texts]

    def embed_query(self, _query: str) -> list[float]:
        return self.query_vector


def controlled_vector(cosine_similarity: float) -> list[float]:
    return [
        cosine_similarity,
        math.sqrt(1 - cosine_similarity**2),
        *([0.0] * 382),
    ]


def use_controlled_embeddings(vectors_by_text: dict[str, list[float]]) -> None:
    service = ControlledEmbeddingService(
        vectors_by_text,
        [1.0] + [0.0] * 383,
    )
    app.dependency_overrides[get_embedding_service] = lambda: service


def register_and_login(client, email):
    registration = client.post(
        "/api/auth/register",
        json={
            "full_name": "Search Tester",
            "email": email,
            "password": PASSWORD,
        },
    )
    assert registration.status_code == 201
    login = client.post(
        "/api/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert login.status_code == 200
    return login.json()["access_token"], UUID(registration.json()["id"])


def upload_text(client, token, filename, content):
    return client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (filename, content.encode(), "text/plain")},
    )


def test_upload_indexes_text_and_search_returns_owner_passage(client, caplog):
    caplog.set_level(logging.INFO)
    token, user_id = register_and_login(client, "search-owner@example.com")
    uploaded = upload_text(
        client,
        token,
        "project-notes.txt",
        "The astronomy project deadline is Friday. "
        "The telescope must be returned to the science lab.",
    )

    assert uploaded.status_code == 201
    document = uploaded.json()
    assert document["indexing_status"] == "completed"
    with Session(app.state.test_engine) as db:
        chunks = db.scalars(
            select(DocumentChunk).where(
                DocumentChunk.user_id == user_id,
                DocumentChunk.document_id == UUID(document["id"]),
            )
        ).all()
        assert len(chunks) == 1
        assert len(chunks[0].embedding) == 384

    response = client.post(
        "/api/search",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "astronomy project deadline"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result_count"] == 1
    result = body["results"][0]
    assert result["document_filename"] == "project-notes.txt"
    assert "deadline is Friday" in result["passage"]
    assert result["chunk_index"] == 0
    assert result["page_start"] is None
    assert -1 <= result["cosine_similarity"] <= 1
    for stage in (
        "document_lookup",
        "text_chunking",
        "embedding_generation",
        "existing_chunk_deletion",
        "new_chunk_insertion",
        "database_flush",
        "transaction_commit",
    ):
        assert f"stage={stage}" in caplog.text
    assert "The astronomy project deadline" not in caplog.text


def test_search_is_strictly_scoped_to_authenticated_user(client):
    owner_token, _ = register_and_login(client, "private-search@example.com")
    stranger_token, _ = register_and_login(client, "stranger-search@example.com")
    uploaded = upload_text(
        client,
        owner_token,
        "private.txt",
        "Rareword quasar observation notes.",
    )
    assert uploaded.status_code == 201

    response = client.post(
        "/api/search",
        headers={"Authorization": f"Bearer {stranger_token}"},
        json={"query": "Rareword quasar observation"},
    )

    assert response.status_code == 200
    assert response.json()["results"] == []
    assert response.json()["indexed_chunk_count"] == 0


def test_search_limit_and_empty_query_validation(client):
    token, _ = register_and_login(client, "search-validation@example.com")

    empty = client.post(
        "/api/search",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "  \n "},
    )
    too_many = client.post(
        "/api/search",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "test", "limit": 11},
    )

    assert empty.status_code == 422
    assert too_many.status_code == 422


def test_search_requires_authentication(client):
    response = client.post("/api/search", json={"query": "private information"})

    assert response.status_code == 401


def test_search_returns_empty_results_when_owner_has_no_indexed_documents(client):
    token, _ = register_and_login(client, "empty-search@example.com")

    response = client.post(
        "/api/search",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "no matching document"},
    )

    assert response.status_code == 200
    assert response.json()["result_count"] == 0
    assert response.json()["results"] == []
    assert response.json()["indexed_chunk_count"] == 0


def test_search_honors_result_limit(client):
    token, _ = register_and_login(client, "search-limit@example.com")
    for index in range(3):
        response = upload_text(
            client,
            token,
            f"notes-{index}.txt",
            f"Semantic search common topic item {index}.",
        )
        assert response.status_code == 201

    response = client.post(
        "/api/search",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "Semantic search common topic", "limit": 2},
    )

    assert response.status_code == 200
    assert response.json()["result_count"] == 2
    assert response.json()["indexed_chunk_count"] == 3


def test_search_keeps_relevant_and_filters_below_threshold(client, monkeypatch):
    monkeypatch.setattr(settings, "search_minimum_similarity", 0.5)
    use_controlled_embeddings(
        {
            "relevant synthetic passage": controlled_vector(0.8),
            "unrelated synthetic passage": controlled_vector(0.2),
        }
    )
    token, _ = register_and_login(client, "threshold-search@example.com")
    assert upload_text(
        client,
        token,
        "relevant.txt",
        "relevant synthetic passage",
    ).status_code == 201
    assert upload_text(
        client,
        token,
        "unrelated.txt",
        "unrelated synthetic passage",
    ).status_code == 201

    response = client.post(
        "/api/search",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "controlled query"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["indexed_chunk_count"] == 2
    assert body["minimum_similarity"] == 0.5
    assert [result["document_filename"] for result in body["results"]] == [
        "relevant.txt"
    ]
    assert body["results"][0]["cosine_similarity"] == pytest.approx(0.8)


def test_search_includes_result_at_similarity_threshold(client, monkeypatch):
    monkeypatch.setattr(settings, "search_minimum_similarity", 0.6)
    use_controlled_embeddings(
        {"boundary synthetic passage": controlled_vector(0.6)}
    )
    token, _ = register_and_login(client, "boundary-search@example.com")
    assert upload_text(
        client,
        token,
        "boundary.txt",
        "boundary synthetic passage",
    ).status_code == 201

    response = client.post(
        "/api/search",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "controlled query"},
    )

    assert response.status_code == 200
    assert response.json()["result_count"] == 1
    assert response.json()["results"][0]["cosine_similarity"] == pytest.approx(0.6)


def test_search_reports_no_qualifying_passages_when_index_is_nonempty(
    client,
    monkeypatch,
):
    monkeypatch.setattr(settings, "search_minimum_similarity", 0.5)
    use_controlled_embeddings(
        {"below-threshold synthetic passage": controlled_vector(0.2)}
    )
    token, _ = register_and_login(client, "below-threshold-search@example.com")
    assert upload_text(
        client,
        token,
        "below-threshold.txt",
        "below-threshold synthetic passage",
    ).status_code == 201

    response = client.post(
        "/api/search",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "controlled query"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["results"] == []
    assert body["result_count"] == 0
    assert body["indexed_chunk_count"] == 1
    assert body["minimum_similarity"] == 0.5


def test_search_applies_limit_to_threshold_qualified_results(client, monkeypatch):
    monkeypatch.setattr(settings, "search_minimum_similarity", 0.5)
    use_controlled_embeddings(
        {
            "highest synthetic passage": controlled_vector(0.9),
            "second synthetic passage": controlled_vector(0.8),
            "below synthetic passage": controlled_vector(0.4),
        }
    )
    token, _ = register_and_login(client, "threshold-limit@example.com")
    for filename, content in (
        ("highest.txt", "highest synthetic passage"),
        ("second.txt", "second synthetic passage"),
        ("below.txt", "below synthetic passage"),
    ):
        assert upload_text(client, token, filename, content).status_code == 201

    response = client.post(
        "/api/search",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "controlled query", "limit": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["indexed_chunk_count"] == 3
    assert body["result_count"] == 1
    assert body["results"][0]["document_filename"] == "highest.txt"


@pytest.mark.parametrize("minimum_similarity", [-1.01, 1.01])
def test_search_minimum_similarity_setting_rejects_out_of_range_values(
    minimum_similarity,
):
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {"search_minimum_similarity": minimum_similarity}
        )


def test_upload_remains_saved_when_embedding_model_is_unavailable(client):
    class BrokenEmbeddingService:
        def embed_texts(self, _texts):
            raise EmbeddingError()

    app.dependency_overrides[get_embedding_service] = (
        lambda: BrokenEmbeddingService()
    )
    token, _ = register_and_login(client, "embedding-failure@example.com")

    response = upload_text(
        client,
        token,
        "still-saved.txt",
        "This remains available as an uploaded document.",
    )

    assert response.status_code == 201
    assert response.json()["processing_status"] == "completed"
    assert response.json()["indexing_status"] == "failed"
    listing = client.get(
        "/api/documents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listing.status_code == 200
    assert listing.json()[0]["original_filename"] == "still-saved.txt"


def test_reindex_is_owner_scoped_and_replaces_previous_chunks(client):
    owner_token, _ = register_and_login(client, "reindex-owner@example.com")
    other_token, _ = register_and_login(client, "reindex-other@example.com")
    uploaded = upload_text(
        client,
        owner_token,
        "reindex.txt",
        "Reindexing should replace existing chunks transactionally.",
    )
    document = uploaded.json()
    document_id = UUID(document["id"])

    with Session(app.state.test_engine) as db:
        old_ids = set(
            db.scalars(
                select(DocumentChunk.id).where(
                    DocumentChunk.document_id == document_id
                )
            )
        )

    forbidden = client.post(
        f"/api/documents/{document_id}/reindex",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    reindexed = client.post(
        f"/api/documents/{document_id}/reindex",
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    assert forbidden.status_code == 404
    assert reindexed.status_code == 200
    assert reindexed.json()["indexing_status"] == "completed"
    with Session(app.state.test_engine) as db:
        new_ids = set(
            db.scalars(
                select(DocumentChunk.id).where(
                    DocumentChunk.document_id == document_id
                )
            )
        )
        assert len(new_ids) == 1
        assert new_ids.isdisjoint(old_ids)


def test_repeated_index_request_does_not_duplicate_chunks(client):
    from app.services.document_indexer import index_document

    token, user_id = register_and_login(client, "idempotent-index@example.com")
    uploaded = upload_text(
        client,
        token,
        "single-index.txt",
        "A completed document should not create duplicate vectors.",
    )
    document_id = UUID(uploaded.json()["id"])
    embedding_service = app.dependency_overrides[get_embedding_service]()

    with Session(app.state.test_engine) as db:
        indexed = index_document(
            db,
            document_id,
            user_id,
            embedding_service,
        )
        chunk_count = db.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
        )

    assert indexed.chunk_count == 1
    assert chunk_count == 1


def test_reindex_recovers_stale_processing_document(client):
    token, _ = register_and_login(client, "stale-reindex@example.com")
    uploaded = upload_text(
        client,
        token,
        "stale-index.txt",
        "A stale processing state should be recoverable by retrying indexing.",
    )
    document_id = UUID(uploaded.json()["id"])
    stale_updated_at = datetime.now(UTC) - timedelta(minutes=30)

    with Session(app.state.test_engine) as db:
        db.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(indexing_status="processing", updated_at=stale_updated_at)
        )
        db.commit()

    reindexed = client.post(
        f"/api/documents/{document_id}/reindex",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert reindexed.status_code == 200
    assert reindexed.json()["indexing_status"] == "completed"


def test_failed_reindex_keeps_previous_chunks_and_marks_status(client, caplog):
    token, _ = register_and_login(client, "reindex-failure@example.com")
    uploaded = upload_text(
        client,
        token,
        "keep-old-index.txt",
        "Existing chunks remain intact if replacement embedding fails.",
    )
    document_id = UUID(uploaded.json()["id"])

    class BrokenEmbeddingService:
        def embed_texts(self, _texts):
            raise EmbeddingError("generation_failed")

    app.dependency_overrides[get_embedding_service] = (
        lambda: BrokenEmbeddingService()
    )
    response = client.post(
        f"/api/documents/{document_id}/reindex",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 503
    assert "stage=embedding_generation" in caplog.text
    assert "exception_class=EmbeddingError" in caplog.text
    assert "Existing chunks remain intact" not in caplog.text
    with Session(app.state.test_engine) as db:
        document = db.get(Document, document_id)
        chunks = db.scalars(
            select(DocumentChunk).where(
                DocumentChunk.document_id == document_id
            )
        ).all()
        assert document.indexing_status == "failed"
        assert len(chunks) == 1


def test_chunk_flush_failure_is_logged_without_sensitive_exception_data(
    client,
    caplog,
):
    token, _ = register_and_login(client, "flush-failure@example.com")
    private_text = "Private document phrase that must never enter diagnostic logs."
    uploaded = upload_text(client, token, "flush-failure.txt", private_text)
    document_id = UUID(uploaded.json()["id"])
    engine = app.state.test_engine

    def fail_chunk_insert(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _many,
    ):
        if statement.lstrip().upper().startswith("INSERT INTO DOCUMENT_CHUNKS"):
            raise IntegrityError(
                "synthetic database failure",
                {},
                RuntimeError("sensitive diagnostic payload"),
            )

    event.listen(engine, "before_cursor_execute", fail_chunk_insert)
    try:
        response = client.post(
            f"/api/documents/{document_id}/reindex",
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        event.remove(engine, "before_cursor_execute", fail_chunk_insert)

    assert response.status_code == 503
    assert "stage=database_flush" in caplog.text
    assert "exception_class=IntegrityError" in caplog.text
    assert "sensitive diagnostic payload" not in caplog.text
    assert private_text not in caplog.text
    with Session(engine) as db:
        document = db.get(Document, document_id)
        chunks = db.scalars(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        ).all()
        assert document.indexing_status == "failed"
        assert len(chunks) == 1


def test_transaction_commit_failure_is_logged_and_rolls_back_replacement(client, caplog):
    from app.services.document_indexer import index_document
    from app.services.document_indexer import IndexingError

    token, user_id = register_and_login(client, "commit-failure@example.com")
    uploaded = upload_text(
        client,
        token,
        "commit-failure.txt",
        "Old chunks must survive a failed transaction commit.",
    )
    document_id = UUID(uploaded.json()["id"])
    embedding_service = app.dependency_overrides[get_embedding_service]()

    with Session(app.state.test_engine) as db:
        commit_count = 0

        def fail_index_commit(session):
            nonlocal commit_count
            commit_count += 1
            if commit_count == 2:
                raise SQLAlchemyError("sensitive commit diagnostic")

        event.listen(db, "before_commit", fail_index_commit)
        try:
            with pytest.raises(IndexingError):
                index_document(
                    db,
                    document_id,
                    user_id,
                    embedding_service,
                    force=True,
                )
        finally:
            event.remove(db, "before_commit", fail_index_commit)

    assert "stage=transaction_commit" in caplog.text
    assert "exception_class=SQLAlchemyError" in caplog.text
    assert "sensitive commit diagnostic" not in caplog.text
    with Session(app.state.test_engine) as db:
        document = db.get(Document, document_id)
        chunks = db.scalars(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        ).all()
        assert document.indexing_status == "failed"
        assert len(chunks) == 1


def test_document_delete_removes_indexed_chunks(client):
    token, _ = register_and_login(client, "delete-indexed@example.com")
    uploaded = upload_text(
        client,
        token,
        "delete-indexed.txt",
        "Chunks should be removed when the source document is deleted.",
    )
    document_id = UUID(uploaded.json()["id"])

    deleted = client.delete(
        f"/api/documents/{document_id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert deleted.status_code == 204
    with Session(app.state.test_engine) as db:
        assert db.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
        ) == 0
        assert db.get(Document, document_id) is None
