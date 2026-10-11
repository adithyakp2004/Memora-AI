import logging
import re
import zipfile
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

import pymupdf
from docx import Document as WordDocument
from docx.document import Document as WordDocumentType
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

MAX_DOCX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_DOCX_ARCHIVE_ENTRIES = 10_000
MAX_PDF_PAGES = 500
logger = logging.getLogger(__name__)


class DocumentProcessingError(ValueError):
    def __init__(
        self,
        message: str,
        status_code: int = 422,
        category: str = "processing_failed",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.category = category


def normalize_extracted_text(
    text: str,
    max_chars: int,
    *,
    empty_message: str = "No extractable text was found in this document.",
    empty_category: str = "no_text",
) -> str:
    normalized_lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        cleaned = re.sub(r"[^\S\n]+", " ", line.replace("\u00a0", " ")).strip()
        normalized_lines.append(cleaned)

    normalized = re.sub(r"\n{3,}", "\n\n", "\n".join(normalized_lines)).strip()
    if not normalized:
        raise DocumentProcessingError(empty_message, category=empty_category)
    if len(normalized) > max_chars:
        raise DocumentProcessingError(
            "The extracted text exceeds the supported document size.",
            status_code=413,
            category="text_too_large",
        )
    return normalized


def _read_pdf(data: bytes, max_chars: int) -> str:
    try:
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            page_count = len(pdf)
            logger.info(
                "PDF opened successfully page_count=%d file_type=.pdf",
                page_count,
            )
            if pdf.needs_pass:
                raise DocumentProcessingError(
                    "Password-protected PDFs are not supported.",
                    category="encrypted_pdf",
                )
            if page_count > MAX_PDF_PAGES:
                raise DocumentProcessingError(
                    "PDFs may contain at most 500 pages.",
                    status_code=413,
                    category="pdf_page_limit",
                )
            if page_count == 0:
                raise DocumentProcessingError(
                    "This PDF contains no pages.",
                    category="pdf_no_pages",
                )
            pages = []
            total_chars = 0
            image_count = 0
            image_backed_page_count = 0
            text_drawing_count = 0
            for page in pdf:
                page_text = page.get_text("text")
                total_chars += len(page_text)
                if total_chars > max_chars:
                    raise DocumentProcessingError(
                        "The extracted text exceeds the supported document size.",
                        status_code=413,
                        category="text_too_large",
                    )
                pages.append(page_text)
                images = page.get_image_info(xrefs=True)
                image_count += len(images)
                page_area = max(page.rect.width * page.rect.height, 1)
                image_area = sum(
                    max(image["bbox"][2] - image["bbox"][0], 0)
                    * max(image["bbox"][3] - image["bbox"][1], 0)
                    for image in images
                )
                if images and image_area / page_area >= 0.5:
                    image_backed_page_count += 1
                text_drawing_count += sum(
                    item[0] in {"fill-text", "stroke-text", "ignore-text"}
                    for item in page.get_bboxlog()
                )
    except DocumentProcessingError:
        raise
    except (pymupdf.FileDataError, pymupdf.EmptyFileError, RuntimeError, ValueError):
        raise DocumentProcessingError("This PDF could not be processed.") from None

    raw_text = "\n\n".join(pages)
    try:
        extracted_text = normalize_extracted_text(raw_text, max_chars)
    except DocumentProcessingError as exc:
        if exc.category != "no_text":
            raise
        logger.warning(
            "PDF text extraction returned no readable characters "
            "page_count=%d file_type=.pdf method=pymupdf raw_char_count=%d "
            "image_count=%d image_backed_pages=%d text_drawing_count=%d "
            "outcome=empty",
            page_count,
            len(raw_text),
            image_count,
            image_backed_page_count,
            text_drawing_count,
        )
        if text_drawing_count:
            raise DocumentProcessingError(
                "This PDF contains text elements that could not be decoded "
                "into readable characters.",
                category="pdf_text_decode_failed",
            ) from None
        if image_backed_page_count:
            raise DocumentProcessingError(
                "This PDF appears to contain page images instead of selectable "
                "text. OCR is not available.",
                category="pdf_likely_image_based",
            ) from None
        raise DocumentProcessingError(
            "No selectable text could be extracted from this PDF.",
            category="pdf_no_selectable_text",
        ) from None

    return extracted_text


def _iter_docx_blocks(
    document: WordDocumentType,
) -> Iterator[Paragraph | Table]:
    for block in document.element.body.iterchildren():
        if isinstance(block, CT_P):
            yield Paragraph(block, document)
        elif isinstance(block, CT_Tbl):
            yield Table(block, document)


def _table_text(table: Table) -> str:
    rows = []
    for row in table.rows:
        cells = [cell.text.strip() for cell in row.cells]
        rows.append(" | ".join(cells))
    return "\n".join(rows)


def _validate_docx_archive(data: bytes) -> None:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            if (
                len(entries) > MAX_DOCX_ARCHIVE_ENTRIES
                or sum(entry.file_size for entry in entries)
                > MAX_DOCX_UNCOMPRESSED_BYTES
                or not any(entry.filename == "word/document.xml" for entry in entries)
            ):
                raise DocumentProcessingError("This DOCX file is invalid or too large.")
            if any(
                entry.file_size > 1_000_000
                and entry.file_size / max(entry.compress_size, 1) > 200
                for entry in entries
            ):
                raise DocumentProcessingError("This DOCX file is invalid or too large.")
    except DocumentProcessingError:
        raise
    except (zipfile.BadZipFile, OSError, ValueError):
        raise DocumentProcessingError("This DOCX file could not be processed.") from None


def _read_docx(data: bytes, max_chars: int) -> str:
    _validate_docx_archive(data)
    try:
        document = WordDocument(BytesIO(data))
        blocks = []
        total_chars = 0
        for block in _iter_docx_blocks(document):
            block_text = block.text if isinstance(block, Paragraph) else _table_text(block)
            total_chars += len(block_text)
            if total_chars > max_chars:
                raise DocumentProcessingError(
                    "The extracted text exceeds the supported document size.",
                    status_code=413,
                    category="text_too_large",
                )
            if block_text.strip():
                blocks.append(block_text)
    except DocumentProcessingError:
        raise
    except Exception:
        raise DocumentProcessingError("This DOCX file could not be processed.") from None

    return normalize_extracted_text("\n\n".join(blocks), max_chars)


def _read_txt(data: bytes, max_chars: int) -> str:
    if b"\x00" in data:
        raise DocumentProcessingError(
            "The TXT file is not valid UTF-8 text.",
            category="invalid_txt_encoding",
        )
    try:
        text = data.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        raise DocumentProcessingError(
            "The TXT file must use UTF-8 encoding.",
            category="invalid_txt_encoding",
        ) from None
    return normalize_extracted_text(text, max_chars)


def extract_text(path: Path, file_type: str, max_chars: int) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        raise DocumentProcessingError(
            "The uploaded file could not be read.",
            status_code=500,
            category="file_read_failed",
        ) from None

    methods = {
        ".pdf": "pymupdf",
        ".docx": "python-docx",
        ".txt": "utf-8",
    }
    method = methods.get(file_type)
    logger.info(
        "Document extraction started file_type=%s file_size_bytes=%d method=%s",
        file_type,
        len(data),
        method or "unsupported",
    )
    try:
        if file_type == ".pdf":
            extracted_text = _read_pdf(data, max_chars)
        elif file_type == ".docx":
            extracted_text = _read_docx(data, max_chars)
        elif file_type == ".txt":
            extracted_text = _read_txt(data, max_chars)
        else:
            raise DocumentProcessingError(
                "This file type is not supported.",
                status_code=415,
                category="unsupported_file_type",
            )
    except DocumentProcessingError as exc:
        logger.warning(
            "Document extraction failed file_type=%s file_size_bytes=%d "
            "method=%s error_category=%s outcome=failed",
            file_type,
            len(data),
            method or "unsupported",
            exc.category,
        )
        raise

    logger.info(
        "Document extraction completed file_type=%s file_size_bytes=%d "
        "method=%s extracted_char_count=%d outcome=completed",
        file_type,
        len(data),
        method,
        len(extracted_text),
    )
    return extracted_text
