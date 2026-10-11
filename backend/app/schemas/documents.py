from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentRead(BaseModel):
    id: UUID
    original_filename: str
    file_type: str
    file_size: int
    processing_status: str
    error_message: str | None
    indexing_status: str
    indexing_error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentContentRead(BaseModel):
    id: UUID
    original_filename: str
    extracted_text: str = Field(max_length=1_000_000)

    model_config = ConfigDict(from_attributes=True)
