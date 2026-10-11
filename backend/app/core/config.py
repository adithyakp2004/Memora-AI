from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    database_url: str | None = None
    app_env: str = "development"
    jwt_secret_key: SecretStr | None = None
    jwt_access_token_expire_minutes: int = Field(default=30, gt=0, le=1440)
    frontend_origin: str = "http://localhost:5173"
    document_storage_dir: Path = BACKEND_DIR / "storage" / "documents"
    document_max_upload_size_mb: int = Field(default=10, gt=0, le=100)
    document_max_extracted_text_chars: int = Field(
        default=1_000_000, gt=0, le=1_000_000
    )
    document_chunk_size_chars: int = Field(default=2_000, gt=100, le=10_000)
    document_chunk_overlap_chars: int = Field(default=400, ge=0, le=2_000)
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_batch_size: int = Field(default=32, gt=0, le=256)
    search_minimum_similarity: float = Field(default=0.0, ge=-1.0, le=1.0)

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_chunk_overlap(self) -> "Settings":
        if self.document_chunk_overlap_chars >= self.document_chunk_size_chars:
            raise ValueError(
                "DOCUMENT_CHUNK_OVERLAP_CHARS must be smaller than "
                "DOCUMENT_CHUNK_SIZE_CHARS."
            )
        return self


settings = Settings()
