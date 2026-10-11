import logging
import re
import uuid
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import delete, inspect, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_active_user
from app.core.config import BACKEND_DIR, settings
from app.db.database import get_db
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.user import User
from app.schemas.documents import DocumentContentRead, DocumentRead
from app.services.document_extractor import DocumentProcessingError, extract_text
from app.services.document_indexer import (
    IndexingError,
    IndexingInProgress,
    index_document,
)
from app.services.embeddings import LocalEmbeddingService, get_embedding_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/documents", tags=["documents"])

SUPPORTED_MIME_TYPES = {
    ".pdf": {"application/pdf", "application/octet-stream"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/octet-stream",
    },
    ".txt": {"text/plain", "application/octet-stream"},
}
MAX_FILENAME_LENGTH = 255


def _safe_original_filename(filename: str | None) -> str:
    if not filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose a file to upload.",
        )
    basename = PureWindowsPath(PurePosixPath(filename).name).name
    basename = "".join(
        character for character in basename if ord(character) >= 32 and ord(character) != 127
    ).strip()
    if not basename or basename in {".", ".."}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The filename is invalid.",
        )
    if len(basename) > MAX_FILENAME_LENGTH:
        suffix = Path(basename).suffix
        basename = f"{basename[: MAX_FILENAME_LENGTH - len(suffix)]}{suffix}"
    return basename


def _validate_file_type(extension: str, content_type: str | None) -> None:
    allowed_types = SUPPORTED_MIME_TYPES.get(extension)
    if allowed_types is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF, DOCX, and TXT documents are supported.",
        )
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    if media_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="The file type does not match its declared media type.",
        )


def _storage_directory(user_id: object) -> Path:
    configured_root = Path(settings.document_storage_dir)
    root = (
        configured_root
        if configured_root.is_absolute()
        else BACKEND_DIR / configured_root
    ).resolve()
    frontend_directory = (BACKEND_DIR.parent / "frontend").resolve()
    user_directory = (root / str(user_id)).resolve()
    if (
        not user_directory.is_relative_to(root)
        or root.is_relative_to(frontend_directory)
    ):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document storage is unavailable.",
        )
    return user_directory


def _stored_file_path(user_id: object, stored_filename: str) -> Path:
    directory = _storage_directory(user_id)
    path = (directory / stored_filename).resolve()
    if (
        not path.is_relative_to(directory)
        or Path(stored_filename).name != stored_filename
        or not re.fullmatch(r"[0-9a-f]{32}\.(pdf|docx|txt)", stored_filename)
    ):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document storage is unavailable.",
        )
    return path


def _remove_upload_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.error("Temporary document cleanup failed (%s).", type(exc).__name__)


def _restore_deleted_file(tombstone_path: Path, stored_path: Path) -> bool:
    try:
        tombstone_path.replace(stored_path)
        return True
    except OSError as exc:
        logger.error("Document file restoration failed (%s).", type(exc).__name__)
        return False


def _validate_signature(path: Path, extension: str) -> None:
    try:
        with path.open("rb") as stored_file:
            header = stored_file.read(1024)
    except OSError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The uploaded file could not be processed.",
        ) from None

    if extension == ".pdf" and b"%PDF-" not in header:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="The file content does not match a PDF document.",
        )
    if extension == ".docx":
        try:
            with zipfile.ZipFile(path) as archive:
                is_docx = any(
                    entry.filename == "word/document.xml"
                    for entry in archive.infolist()
                )
        except (OSError, zipfile.BadZipFile):
            is_docx = False
        if not is_docx:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="The file content does not match a DOCX document.",
            )
    if extension == ".txt" and b"\x00" in header:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="The TXT file must contain UTF-8 text.",
        )


def _find_owned_document(
    db: Session,
    document_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Document:
    document = db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.user_id == user_id,
        )
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )
    return document


@router.post(
    "/upload",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
)
def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
    embedding_service: LocalEmbeddingService = Depends(get_embedding_service),
) -> DocumentRead:
    original_filename = _safe_original_filename(file.filename)
    extension = Path(original_filename).suffix.lower()
    _validate_file_type(extension, file.content_type)

    stored_filename = f"{uuid.uuid4().hex}{extension}"
    user_directory = _storage_directory(current_user.id)
    stored_path = _stored_file_path(current_user.id, stored_filename)
    maximum_bytes = settings.document_max_upload_size_mb * 1024 * 1024
    file_size = 0

    try:
        user_directory.mkdir(parents=True, exist_ok=True)
        with stored_path.open("xb") as destination:
            while chunk := file.file.read(64 * 1024):
                file_size += len(chunk)
                if file_size > maximum_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            "The file exceeds the "
                            f"{settings.document_max_upload_size_mb} MB upload limit."
                        ),
                    )
                destination.write(chunk)
        if file_size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Empty files cannot be uploaded.",
            )
        _validate_signature(stored_path, extension)
        extracted_text = extract_text(
            stored_path,
            extension,
            settings.document_max_extracted_text_chars,
        )
    except HTTPException:
        _remove_upload_file(stored_path)
        raise
    except DocumentProcessingError as exc:
        _remove_upload_file(stored_path)
        raise HTTPException(
            status_code=exc.status_code,
            detail=str(exc),
        ) from None
    except OSError as exc:
        _remove_upload_file(stored_path)
        logger.warning("Document upload storage failed (%s).", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The document could not be stored.",
        ) from None
    except Exception as exc:
        _remove_upload_file(stored_path)
        logger.warning("Document processing failed (%s).", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The document could not be processed.",
        ) from None

    document = Document(
        user_id=current_user.id,
        original_filename=original_filename,
        stored_filename=stored_filename,
        file_type=extension,
        file_size=file_size,
        extracted_text=extracted_text,
        processing_status="completed",
        indexing_status="pending",
    )
    try:
        db.add(document)
        db.flush()
        response = DocumentRead.model_validate(document)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        _remove_upload_file(stored_path)
        logger.warning("Document metadata save failed (%s).", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The document could not be saved.",
        ) from None

    try:
        index_document(
            db,
            document.id,
            current_user.id,
            embedding_service,
        )
    except IndexingError:
        db.refresh(document)

    response = DocumentRead.model_validate(document)
    return response


@router.post("/{document_id}/reindex", response_model=DocumentRead)
def reindex_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
    embedding_service: LocalEmbeddingService = Depends(get_embedding_service),
) -> DocumentRead:
    try:
        result = index_document(
            db,
            document_id,
            current_user.id,
            embedding_service,
            force=True,
        )
    except IndexingInProgress as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from None
    except IndexingError as exc:
        status_code = (
            status.HTTP_404_NOT_FOUND
            if exc.category == "not_found"
            else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        raise HTTPException(
            status_code=status_code,
            detail=str(exc),
        ) from None
    return DocumentRead.model_validate(result.document)


@router.get("", response_model=list[DocumentRead])
def list_documents(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> list[DocumentRead]:
    documents = db.scalars(
        select(Document)
        .where(Document.user_id == current_user.id)
        .order_by(Document.created_at.desc(), Document.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return [DocumentRead.model_validate(document) for document in documents]


@router.get("/{document_id}", response_model=DocumentRead)
def get_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> DocumentRead:
    document = _find_owned_document(db, document_id, current_user.id)
    return DocumentRead.model_validate(document)


@router.get("/{document_id}/content", response_model=DocumentContentRead)
def get_document_content(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> DocumentContentRead:
    document = _find_owned_document(db, document_id, current_user.id)
    return DocumentContentRead.model_validate(document)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> None:
    tombstone_path: Path | None = None
    try:
        document = _find_owned_document(db, document_id, current_user.id)
        stored_path = _stored_file_path(current_user.id, document.stored_filename)
        candidate_tombstone = stored_path.with_name(f"{uuid.uuid4().hex}.delete")
        if stored_path.exists():
            try:
                stored_path.replace(candidate_tombstone)
            except OSError as exc:
                logger.warning("Document removal failed (%s).", type(exc).__name__)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="The document could not be deleted.",
                ) from None
            tombstone_path = candidate_tombstone
        if inspect(db.get_bind()).has_table("document_chunks"):
            db.execute(
                delete(DocumentChunk).where(
                    DocumentChunk.document_id == document.id,
                    DocumentChunk.user_id == current_user.id,
                )
            )
        db.delete(document)
        db.commit()
    except HTTPException:
        if (
            tombstone_path is not None
            and tombstone_path.exists()
            and not _restore_deleted_file(tombstone_path, stored_path)
        ):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="The document could not be restored after deletion failed.",
            ) from None
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        if (
            tombstone_path is not None
            and tombstone_path.exists()
            and not _restore_deleted_file(tombstone_path, stored_path)
        ):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="The document could not be restored after deletion failed.",
            ) from None
        logger.warning("Document record deletion failed (%s).", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The document could not be deleted.",
        ) from None

    if tombstone_path is not None and tombstone_path.exists():
        try:
            tombstone_path.unlink()
        except OSError as exc:
            logger.warning("Deleted document file cleanup failed (%s).", type(exc).__name__)
