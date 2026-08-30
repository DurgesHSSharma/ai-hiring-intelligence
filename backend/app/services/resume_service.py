"""Resume batch upload orchestration (Architecture.md 7.1). Raises domain
exceptions from core/exceptions.py; never HTTPException (Rules.md 5.2).

Two failure tiers, deliberately handled differently:
  - Tier 1 (file validation: extension/MIME/magic-bytes/size) means the
    upload was never a resume at all — no candidate row, nothing written to
    disk, recorded per-file only in the response.
  - Tier 2 (extraction failure, or fewer than MIN_RESUME_TEXT_LENGTH chars)
    means a real file was accepted and stored but couldn't be turned into
    usable text — PRD F3.7 requires this to still create a candidate row
    with parse_status=PARSE_FAILED and a readable parse_error, not be
    silently dropped, so the recruiter can see it and download the file.

Field and skill extraction (Phase 5) only run on the success path —
Architecture.md 7.1's flow diagram routes both the extraction-failure and
the too-short-text guard straight to "parse_failed, continue," never
reaching field_extractor. A parse_failed row's fields stay None/empty,
exactly as they were before this phase existed.
"""
import logging

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.core.enums import ApplicationStatus, ParseStatus
from app.core.exceptions import FileValidationError, NotFoundError, ValidationError
from app.ml.extraction.field_extractor import ExtractedFields, extract_all
from app.ml.extraction.text_cleaner import clean_text
from app.ml.extraction.text_extractor import TextExtractionError, extract_text
from app.ml.skills.skill_matcher import MatchedSkill, match_skills
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.candidate_skill import CandidateSkill
from app.models.job import Job
from app.schemas.resume import ResumeUploadResponse, ResumeUploadResult
from app.utils.files import delete_stored_file, save_upload_file, validate_and_read_upload

logger = logging.getLogger(__name__)

MIN_RESUME_TEXT_LENGTH = 100

_EMPTY_FIELDS = ExtractedFields(
    name=None, email=None, phone=None, education=None, education_level=None, experience_years=None
)


def upload_resumes(db: Session, job_id: int, files: list[UploadFile]) -> ResumeUploadResponse:
    job = db.get(Job, job_id)
    if job is None:
        raise NotFoundError("Job not found.", code="JOB_NOT_FOUND", details={"job_id": job_id})

    # Request-level checks: not about any one file, so these abort the whole
    # call rather than being recorded per-file. Everything past this point
    # is file-level and always lands in `results`, batch always returns 200.
    if not files:
        raise ValidationError("No files were provided.", code="NO_FILES_PROVIDED")
    if len(files) > settings.MAX_FILES_PER_BATCH:
        raise ValidationError(
            f"Batch exceeds the {settings.MAX_FILES_PER_BATCH}-file limit.",
            code="BATCH_LIMIT_EXCEEDED",
            details={"file_count": len(files), "max_allowed": settings.MAX_FILES_PER_BATCH},
        )

    results = [_process_one_file(db, job_id, upload) for upload in files]
    uploaded_count = sum(1 for r in results if r.status == ParseStatus.PARSED)

    return ResumeUploadResponse(
        job_id=job_id, uploaded=uploaded_count, failed=len(files) - uploaded_count, results=results
    )


def _find_existing_candidate(db: Session, email: str | None) -> Candidate | None:
    """None short-circuits before any query runs — Candidate.email == None
    would otherwise become a SQLAlchemy `IS NULL` comparison (not a raw SQL
    `= NULL`, which would never match anything), and every Phase-4 candidate
    has a NULL email. Without this guard, the first resume with no
    extractable email would "dedupe-match" every one of them (Memory.md
    decision 18's carry-forward).
    """
    if email is None:
        return None
    return db.query(Candidate).filter(Candidate.email == email).first()


def _get_or_create_application(db: Session, candidate_id: int, job_id: int) -> None:
    """Get-or-create, not a blind insert: applications has a unique
    constraint on (candidate_id, job_id), and re-uploading the same resume
    to the SAME job (as opposed to a different one) must not violate it.
    An existing application's status is left untouched — re-uploading a
    resume must not silently regress a "shortlisted" application back to
    "new".
    """
    existing = (
        db.query(Application)
        .filter(Application.candidate_id == candidate_id, Application.job_id == job_id)
        .first()
    )
    if existing is None:
        db.add(Application(candidate_id=candidate_id, job_id=job_id, status=ApplicationStatus.NEW))


def _replace_skills(db: Session, candidate_id: int, matches: list[MatchedSkill]) -> None:
    db.query(CandidateSkill).filter(CandidateSkill.candidate_id == candidate_id).delete()
    for match in matches:
        db.add(
            CandidateSkill(
                candidate_id=candidate_id,
                skill_name=match.canonical,
                skill_type=match.skill_type,
                source=match.source,
            )
        )


def _process_one_file(db: Session, job_id: int, upload: UploadFile) -> ResumeUploadResult:
    filename = upload.filename or "(unnamed file)"

    try:
        content, extension = validate_and_read_upload(upload)
    except FileValidationError as exc:
        return ResumeUploadResult(
            filename=filename, status=ParseStatus.PARSE_FAILED, code=exc.code, error=exc.message
        )

    storage_name = save_upload_file(content, extension)

    parse_status = ParseStatus.PARSED
    code: str | None = None
    parse_error: str | None = None
    try:
        cleaned = clean_text(extract_text(content, extension))
    except TextExtractionError as exc:
        parse_status = ParseStatus.PARSE_FAILED
        code = "RESUME_PARSE_FAILED"
        parse_error = str(exc)
        resume_text = ""
    else:
        resume_text = cleaned
        if len(cleaned) < MIN_RESUME_TEXT_LENGTH:
            parse_status = ParseStatus.PARSE_FAILED
            code = "RESUME_TEXT_TOO_SHORT"
            parse_error = (
                f"Extracted text is only {len(cleaned)} characters "
                f"(minimum {MIN_RESUME_TEXT_LENGTH}) — likely a scanned image with no text layer."
            )

    if parse_status == ParseStatus.PARSED:
        fields = extract_all(resume_text)
        matched_skills = match_skills(resume_text)
    else:
        fields = _EMPTY_FIELDS
        matched_skills = []

    # Dedupe by email (F3.6): a match means this candidate has been seen
    # before, possibly for a different job. Their record is updated with
    # this upload's fresher extraction rather than creating a second row.
    old_resume_path: str | None = None
    candidate = _find_existing_candidate(db, fields.email)
    if candidate is not None:
        old_resume_path = candidate.resume_path
        candidate.name = fields.name
        candidate.phone = fields.phone
        candidate.resume_path = storage_name
        candidate.resume_filename = filename
        candidate.resume_text = resume_text
        # Phase 7 (F5.5): resume_text just changed, so any cached embedding
        # was computed from the OLD text and would silently score the
        # wrong document. Reset it; scoring_service.py recomputes lazily
        # on the next embedding-mode scoring run.
        candidate.embedding = None
        candidate.education = fields.education
        candidate.education_level = fields.education_level
        candidate.experience_years = fields.experience_years
        candidate.projects = fields.projects
        candidate.certifications = fields.certifications
        candidate.parse_status = parse_status
        candidate.parse_error = parse_error
    else:
        candidate = Candidate(
            name=fields.name,
            email=fields.email,
            phone=fields.phone,
            resume_path=storage_name,
            resume_filename=filename,
            resume_text=resume_text,
            education=fields.education,
            education_level=fields.education_level,
            experience_years=fields.experience_years,
            projects=fields.projects,
            certifications=fields.certifications,
            parse_status=parse_status,
            parse_error=parse_error,
        )
        db.add(candidate)

    db.flush()
    _replace_skills(db, candidate.id, matched_skills)
    _get_or_create_application(db, candidate.id, job_id)
    db.commit()
    db.refresh(candidate)

    # Old file deleted only after the commit succeeds — same ordering as
    # candidate_service.delete_candidate, for the same reason: a failed
    # commit must never leave a live row pointing at an already-deleted file.
    if old_resume_path is not None and old_resume_path != storage_name:
        try:
            delete_stored_file(old_resume_path)
        except OSError:
            logger.warning(
                "Failed to delete superseded resume file %s for candidate %s", old_resume_path, candidate.id
            )

    return ResumeUploadResult(
        filename=filename, status=parse_status, candidate_id=candidate.id, code=code, error=parse_error
    )
