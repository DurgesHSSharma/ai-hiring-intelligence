"""File upload validation and storage (Rules.md 5.4, Architecture.md 7.1).

Four checks, cheapest first: extension, declared MIME type, magic bytes,
size. All four raise FileValidationError with a specific code — callers
decide what to do with a failure (resume_service.py records it per-file).
The client's original filename is used for display only; it never
participates in building a filesystem path.
"""
import zipfile
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.config import settings
from app.core.exceptions import FileValidationError

# Anchored to backend/ via path arithmetic from this file's own location, not
# to the process's cwd — the same fix as config.py's ENV_FILE_PATH (Phase 1).
# Without this, UPLOAD_DIR="./storage" would resolve differently depending on
# whether uvicorn or pytest was launched from backend/ or the repo root.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
UPLOAD_DIR = (_BACKEND_ROOT / settings.UPLOAD_DIR).resolve()

_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"
# The actual OOXML marker for a Word package specifically. PK\x03\x04 alone
# only proves "this is some zip" — true of .xlsx, .pptx, .jar, or a renamed
# plain .zip too. An .xlsx has xl/ at this position instead, a .pptx has
# ppt/, so a renamed spreadsheet or an arbitrary zip fails here even though
# it passed the 4-byte signature check.
_DOCX_REQUIRED_ENTRY = "word/document.xml"

_ALLOWED_CONTENT_TYPES: dict[str, set[str]] = {
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
}


def _get_extension(filename: str | None) -> str:
    if not filename:
        return ""
    return Path(filename).suffix.lower()


def _check_magic_bytes(content: bytes, extension: str) -> None:
    if extension == ".pdf":
        if not content.startswith(_PDF_MAGIC):
            raise FileValidationError(
                "File content does not match a PDF.", code="UNSUPPORTED_FILE_TYPE", http_status=415
            )
        return

    if not content.startswith(_ZIP_MAGIC):
        raise FileValidationError(
            "File content does not match a DOCX package.", code="UNSUPPORTED_FILE_TYPE", http_status=415
        )
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            if _DOCX_REQUIRED_ENTRY not in archive.namelist():
                raise FileValidationError(
                    "File is a zip archive but not a Word document.",
                    code="UNSUPPORTED_FILE_TYPE",
                    http_status=415,
                )
    except zipfile.BadZipFile:
        raise FileValidationError(
            "File content does not match a DOCX package.", code="UNSUPPORTED_FILE_TYPE", http_status=415
        )


def validate_and_read_upload(upload: UploadFile) -> tuple[bytes, str]:
    """Validates one uploaded file and returns (content, extension).

    Raises FileValidationError (415 UNSUPPORTED_FILE_TYPE or 413
    FILE_TOO_LARGE) on any failure. The read is capped at
    MAX_UPLOAD_SIZE_MB + 1 bytes regardless of what the client claims about
    size, so a hostile Content-Length can't force an unbounded read before
    the size check ever runs.
    """
    extension = _get_extension(upload.filename)
    if extension not in _ALLOWED_CONTENT_TYPES:
        raise FileValidationError(
            f"Unsupported file extension: {extension or '(none)'!r}. Only .pdf and .docx are accepted.",
            code="UNSUPPORTED_FILE_TYPE",
            http_status=415,
        )

    if upload.content_type not in _ALLOWED_CONTENT_TYPES[extension]:
        raise FileValidationError(
            f"Unsupported content type {upload.content_type!r} for a {extension} file.",
            code="UNSUPPORTED_FILE_TYPE",
            http_status=415,
        )

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    content = upload.file.read(max_bytes + 1)

    _check_magic_bytes(content, extension)

    # Checked last, but not extra I/O: this is just a length check on the
    # buffer the magic-byte check already needed in memory.
    if len(content) > max_bytes:
        raise FileValidationError(
            f"File exceeds the {settings.MAX_UPLOAD_SIZE_MB} MB limit.", code="FILE_TOO_LARGE", http_status=413
        )

    return content, extension


def save_upload_file(content: bytes, extension: str) -> str:
    """Writes validated bytes under a generated UUID name and returns that
    name — never the client's filename — which is what gets stored in
    candidates.resume_path.
    """
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    storage_name = f"{uuid4().hex}{extension}"
    (UPLOAD_DIR / storage_name).write_bytes(content)
    return storage_name


def resolve_stored_path(storage_name: str) -> Path:
    return UPLOAD_DIR / storage_name


def delete_stored_file(storage_name: str) -> None:
    resolve_stored_path(storage_name).unlink(missing_ok=True)
