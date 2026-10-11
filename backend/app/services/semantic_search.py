import math
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.services.embeddings import EmbeddingError, LocalEmbeddingService
from app.schemas.search import SearchResult


class SearchUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class SearchResults:
    results: list[SearchResult]
    indexed_chunk_count: int


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    similarity = sum(a * b for a, b in zip(left, right, strict=True)) / (
        left_norm * right_norm
    )
    return max(-1.0, min(1.0, similarity))


def search_documents(
    db: Session,
    user_id: UUID,
    query: str,
    limit: int,
    minimum_similarity: float,
    embedding_service: LocalEmbeddingService,
) -> SearchResults:
    try:
        if db.get_bind().dialect.name == "postgresql":
            extension_ready = db.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_extension "
                    "WHERE extname = 'vector')"
                )
            ).scalar_one()
            if not extension_ready:
                raise SearchUnavailableError(
                    "PostgreSQL pgvector is not enabled for semantic search."
                )
    except SQLAlchemyError:
        raise SearchUnavailableError(
            "Vector search is unavailable. Check the PostgreSQL pgvector setup."
        ) from None

    try:
        query_vector = embedding_service.embed_query(query)
    except EmbeddingError:
        raise SearchUnavailableError(
            "The local embedding model is unavailable."
        ) from None

    statement = (
        select(DocumentChunk, Document.original_filename)
        .join(
            Document,
            (Document.id == DocumentChunk.document_id)
            & (Document.user_id == DocumentChunk.user_id),
        )
        .where(
            DocumentChunk.user_id == user_id,
            Document.user_id == user_id,
            Document.indexing_status == "completed",
        )
    )
    try:
        indexed_chunk_count = db.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .join(
                Document,
                (Document.id == DocumentChunk.document_id)
                & (Document.user_id == DocumentChunk.user_id),
            )
            .where(
                DocumentChunk.user_id == user_id,
                Document.user_id == user_id,
                Document.indexing_status == "completed",
            )
        )
        if db.get_bind().dialect.name == "postgresql":
            distance = DocumentChunk.embedding.cosine_distance(query_vector)
            rows = db.execute(
                statement.add_columns(distance.label("distance"))
                .where(distance <= 1.0 - minimum_similarity)
                .order_by(distance)
                .limit(limit)
            ).all()
            scored = [
                (chunk, filename, 1.0 - float(distance_value))
                for chunk, filename, distance_value in rows
            ]
        else:
            rows = db.execute(statement).all()
            scored = []
            for chunk, filename in rows:
                similarity = _cosine_similarity(
                    list(chunk.embedding),
                    query_vector,
                )
                if similarity >= minimum_similarity:
                    scored.append((chunk, filename, similarity))
            scored.sort(key=lambda row: row[2], reverse=True)
            scored = scored[:limit]
    except SQLAlchemyError:
        raise SearchUnavailableError(
            "Vector search is unavailable. Check the PostgreSQL pgvector setup."
        ) from None

    results = [
        SearchResult(
            document_id=chunk.document_id,
            document_filename=filename,
            chunk_id=chunk.id,
            chunk_index=chunk.chunk_index,
            passage=chunk.chunk_text,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            cosine_similarity=similarity,
        )
        for chunk, filename, similarity in scored
    ]
    return SearchResults(
        results=results,
        indexed_chunk_count=indexed_chunk_count or 0,
    )
