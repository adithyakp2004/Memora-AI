import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_active_user
from app.core.config import settings
from app.db.database import get_db
from app.models.user import User
from app.schemas.search import SearchRequest, SearchResponse
from app.services.embeddings import LocalEmbeddingService, get_embedding_service
from app.services.semantic_search import SearchUnavailableError, search_documents

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("", response_model=SearchResponse)
def semantic_search(
    payload: SearchRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
    embedding_service: LocalEmbeddingService = Depends(get_embedding_service),
) -> SearchResponse:
    try:
        search_results = search_documents(
            db,
            current_user.id,
            payload.query,
            payload.limit,
            settings.search_minimum_similarity,
            embedding_service,
        )
    except SearchUnavailableError as exc:
        logger.warning(
            "Semantic search unavailable user_id=%s error_category=%s",
            current_user.id,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from None

    return SearchResponse(
        query=payload.query,
        result_count=len(search_results.results),
        results=search_results.results,
        indexed_chunk_count=search_results.indexed_chunk_count,
        minimum_similarity=settings.search_minimum_similarity,
    )
