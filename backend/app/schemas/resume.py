from pydantic import BaseModel

from app.core.enums import ParseStatus


class ResumeUploadResult(BaseModel):
    filename: str
    status: ParseStatus
    # None for a Tier-1 validation failure (never became a candidate at
    # all); set for both a successful parse and a Tier-2 parse failure,
    # since PRD F3.7 requires a parse_failed row to exist and be visible.
    candidate_id: int | None = None
    # Stable machine-readable reason (Rules.md 5.3), e.g. UNSUPPORTED_FILE_TYPE,
    # FILE_TOO_LARGE, RESUME_PARSE_FAILED, RESUME_TEXT_TOO_SHORT. None on success.
    code: str | None = None
    error: str | None = None


class ResumeUploadResponse(BaseModel):
    job_id: int
    uploaded: int
    failed: int
    results: list[ResumeUploadResult]
