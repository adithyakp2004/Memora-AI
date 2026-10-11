import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.services.embeddings import EmbeddingError, LocalEmbeddingService
from app.services.text_chunker import chunk_text

logger = logging.getLogger(__name__)
INDEXING_STALE_AFTER = timedelta(minutes=15)


def _log_stage_failure(
    stage: str,
    document_id: UUID,
    exc: Exception,
    *,
    chunk_count: int | None = None,
    embedding_dimension: int | None = None,
) -> None:
    original = getattr(exc, "orig", None)
    sqlstate = (
        getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
        if isinstance(exc, SQLAlchemyError)
        else None
    )
    diagnostic = getattr(original, "diag", None)
    constraint = getattr(diagnostic, "constraint_name", None)
    logger.error(
        "Document indexing stage failed stage=%s exception_class=%s "
        "sqlstate=%s constraint=%s document_id=%s chunk_count=%s "
        "embedding_dimension=%s",
        stage,
        type(exc).__name__,
        sqlstate,
        constraint,
        document_id,
        chunk_count,
        embedding_dimension,
    )


class IndexingError(RuntimeError):
    def __init__(self, message: str, category: str = "indexing_failed") -> None:
        super().__init__(message)
        self.category = category


class IndexingInProgress(IndexingError):
    def __init__(self) -> None:
        super().__init__("Document indexing is already in progress.", "in_progress")


@dataclass(frozen=True)
class IndexedDocument:
    document: Document
    chunk_count: int


def index_document(
    db: Session,
    document_id: UUID,
    user_id: UUID,
    embedding_service: LocalEmbeddingService,
    *,
    force: bool = False,
) -> IndexedDocument:
    stage = "document_lookup"
    try:
        document = db.scalar(
            select(Document)
            .where(Document.id == document_id, Document.user_id == user_id)
            .with_for_update()
        )
    except SQLAlchemyError as exc:
        db.rollback()
        _log_stage_failure(stage, document_id, exc)
        raise IndexingError(
            "Document indexing is temporarily unavailable.",
            "database_unavailable",
        ) from None

    if document is None:
        logger.warning(
            "Document indexing validation failed stage=%s reason=not_found "
            "document_id=%s",
            stage,
            document_id,
        )
        raise IndexingError("Document not found.", "not_found")
    logger.info(
        "Document indexing stage completed stage=%s document_id=%s",
        stage,
        document_id,
    )

    if db.get_bind().dialect.name == "postgresql":
        stage = "pgvector_availability_check"
        try:
            extension_ready = db.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_extension "
                    "WHERE extname = 'vector')"
                )
            ).scalar_one()
        except SQLAlchemyError as exc:
            db.rollback()
            _log_stage_failure(stage, document_id, exc)
            raise IndexingError(
                "The document was saved but vector storage is unavailable.",
                "vector_storage_unavailable",
            ) from None
        if not extension_ready:
            document.indexing_status = "failed"
            document.indexing_error = (
                "pgvector must be installed and enabled to index documents."
            )
            try:
                db.commit()
            except SQLAlchemyError as exc:
                db.rollback()
                _log_stage_failure("failure_state_commit", document_id, exc)
                raise IndexingError(
                    "The document was saved but vector storage is unavailable.",
                    "vector_storage_unavailable",
                ) from None
            logger.warning(
                "Document indexing validation failed stage=%s "
                "reason=pgvector_not_enabled document_id=%s",
                stage,
                document_id,
            )
            raise IndexingError(
                "pgvector is not enabled for document indexing.",
                "pgvector_not_enabled",
            )
        logger.info(
            "Document indexing stage completed stage=%s document_id=%s",
            stage,
            document_id,
        )

    stage = "existing_chunk_check"
    try:
        existing_count = db.scalar(
            select(DocumentChunk.id)
            .where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.user_id == user_id,
            )
            .limit(1)
        )
    except SQLAlchemyError as exc:
        db.rollback()
        _log_stage_failure(stage, document_id, exc)
        _mark_failed(db, document_id, user_id, failure_stage=stage)
        raise IndexingError(
            "Vector storage is unavailable for document indexing.",
            "vector_storage_unavailable",
        ) from None

    if document.indexing_status == "processing":
        updated_at = document.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        stale_for = datetime.now(UTC) - updated_at
        if stale_for <= INDEXING_STALE_AFTER:
            logger.warning(
                "Document indexing validation failed stage=%s "
                "reason=already_processing document_id=%s",
                stage,
                document_id,
            )
            raise IndexingInProgress()
        logger.warning(
            "Recovering stale document indexing document_id=%s stale_for_seconds=%d",
            document_id,
            int(stale_for.total_seconds()),
        )
    if document.indexing_status == "completed" and existing_count and not force:
        return IndexedDocument(
            document=document,
            chunk_count=db.scalar(
                select(func.count())
                .select_from(DocumentChunk)
                .where(
                    DocumentChunk.document_id == document_id,
                    DocumentChunk.user_id == user_id,
                )
            ),
        )

    stage = "processing_status_commit"
    try:
        document.indexing_status = "processing"
        document.indexing_error = None
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        _log_stage_failure(stage, document_id, exc)
        _mark_failed(db, document_id, user_id, failure_stage=stage)
        raise IndexingError(
            "The document was saved but could not be indexed.",
            "database_unavailable",
        ) from None

    chunks: list[str] = []
    embedding_dimension: int | None = None
    try:
        stage = "text_chunking"
        chunks = chunk_text(
            document.extracted_text,
            chunk_size_chars=settings.document_chunk_size_chars,
            overlap_chars=settings.document_chunk_overlap_chars,
        )
        if not chunks:
            raise IndexingError("The document has no text to index.", "empty_text")
        logger.info(
            "Document indexing stage completed stage=%s document_id=%s chunk_count=%d",
            stage,
            document_id,
            len(chunks),
        )

        stage = "embedding_generation"
        vectors = embedding_service.embed_texts(chunks)
        if len(vectors) != len(chunks):
            raise IndexingError("Embedding output was incomplete.", "invalid_output")
        dimensions = {len(vector) for vector in vectors}
        embedding_dimension = dimensions.pop() if len(dimensions) == 1 else None
        logger.info(
            "Document indexing stage completed stage=%s document_id=%s "
            "chunk_count=%d embedding_dimension=%s",
            stage,
            document_id,
            len(chunks),
            embedding_dimension,
        )

        stage = "existing_chunk_deletion"
        db.execute(
            delete(DocumentChunk).where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.user_id == user_id,
            )
        )
        logger.info(
            "Document indexing stage completed stage=%s document_id=%s",
            stage,
            document_id,
        )

        stage = "new_chunk_insertion"
        db.add_all(
            DocumentChunk(
                document_id=document_id,
                user_id=user_id,
                chunk_index=index,
                chunk_text=chunk,
                embedding=vector,
            )
            for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
        )
        logger.info(
            "Document indexing stage completed stage=%s document_id=%s "
            "chunk_count=%d embedding_dimension=%s",
            stage,
            document_id,
            len(chunks),
            embedding_dimension,
        )

        stage = "database_flush"
        db.flush()
        logger.info(
            "Document indexing stage completed stage=%s document_id=%s "
            "chunk_count=%d embedding_dimension=%s",
            stage,
            document_id,
            len(chunks),
            embedding_dimension,
        )

        document.indexing_status = "completed"
        document.indexing_error = None
        stage = "transaction_commit"
        db.commit()
        logger.info(
            "Document indexing stage completed stage=%s document_id=%s "
            "chunk_count=%d",
            stage,
            document_id,
            len(chunks),
        )
        return IndexedDocument(document=document, chunk_count=len(chunks))
    except (EmbeddingError, IndexingError) as exc:
        db.rollback()
        _log_stage_failure(
            stage,
            document_id,
            exc,
            chunk_count=len(chunks) if chunks else None,
            embedding_dimension=embedding_dimension,
        )
        _mark_failed(db, document_id, user_id, failure_stage=stage)
        logger.warning(
            "Document indexing failed stage=%s document_id=%s error_category=%s",
            stage,
            document_id,
            exc.category,
        )
        raise IndexingError(
            "The document was saved but could not be indexed.",
            exc.category,
        ) from None
    except SQLAlchemyError as exc:
        db.rollback()
        _log_stage_failure(
            stage,
            document_id,
            exc,
            chunk_count=len(chunks) if chunks else None,
            embedding_dimension=embedding_dimension,
        )
        _mark_failed(db, document_id, user_id, failure_stage=stage)
        raise IndexingError(
            "Vector storage is unavailable for document indexing.",
            "vector_storage_unavailable",
        ) from None
    except Exception as exc:
        db.rollback()
        _log_stage_failure(
            stage,
            document_id,
            exc,
            chunk_count=len(chunks) if chunks else None,
            embedding_dimension=embedding_dimension,
        )
        _mark_failed(db, document_id, user_id, failure_stage=stage)
        raise IndexingError(
            "The document was saved but could not be indexed.",
            "indexing_failed",
        ) from None


def _mark_failed(
    db: Session,
    document_id: UUID,
    user_id: UUID,
    *,
    failure_stage: str,
) -> None:
    stage = "failure_state_update"
    try:
        document = db.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.user_id == user_id,
            )
        )
        if document is not None:
            document.indexing_status = "failed"
            document.indexing_error = (
                "Local embedding or vector storage setup is unavailable."
            )
            db.commit()
            logger.info(
                "Document indexing failure state recorded stage=%s "
                "failure_stage=%s document_id=%s",
                stage,
                failure_stage,
                document_id,
            )
    except SQLAlchemyError as exc:
        db.rollback()
        _log_stage_failure(stage, document_id, exc)
        logger.error(
            "Document indexing failure state update failed "
            "failure_stage=%s document_id=%s",
            failure_stage,
            document_id,
        )
