from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2_000)
    limit: int = Field(default=5, ge=1, le=10)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Search query cannot be empty.")
        return normalized


class SearchResult(BaseModel):
    document_id: UUID
    document_filename: str
    chunk_id: UUID
    chunk_index: int
    passage: str
    page_start: int | None
    page_end: int | None
    cosine_similarity: float


class SearchResponse(BaseModel):
    query: str
    result_count: int
    results: list[SearchResult]
    indexed_chunk_count: int
    minimum_similarity: float
