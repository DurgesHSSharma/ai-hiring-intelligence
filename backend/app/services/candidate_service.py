"""Candidate read/delete and application status updates. Raises domain
exceptions from core/exceptions.py; never HTTPException (Rules.md 5.2).
"""
import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session, selectinload

from app.core.enums import ApplicationStatus
from app.core.exceptions import NotFoundError
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.candidate_skill import CandidateSkill
from app.schemas.candidate import (
    CandidateDetailResponse,
    CandidateResponse,
    CandidateSkillOut,
    GroupedSkills,
)
from app.schemas.common import DeletedResponse, Page
from app.utils.files import delete_stored_file, resolve_stored_path

logger = logging.getLogger(__name__)

# Mirrors utils/files.py's validated extensions — used only to set a correct
# download Content-Type, not for any validation decision.
_RESUME_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@dataclass
class ResumeFile:
    """Plain data, not a Starlette response: services/ must not import HTTP
    response classes (Rules.md 4.2). api/candidates.py builds the actual
    FileResponse from this.
    """

    path: Path
    media_type: str
    display_filename: str


def _get_candidate_or_404(db: Session, candidate_id: int) -> Candidate:
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise NotFoundError(
            "Candidate not found.", code="CANDIDATE_NOT_FOUND", details={"candidate_id": candidate_id}
        )
    return candidate


def _get_application_or_404(db: Session, application_id: int) -> Application:
    application = db.get(Application, application_id)
    if application is None:
        raise NotFoundError(
            "Application not found.",
            code="APPLICATION_NOT_FOUND",
            details={"application_id": application_id},
        )
    return application


def list_candidates(db: Session, *, page: int, page_size: int) -> Page[CandidateResponse]:
    # No search/filter/sort here — that's PRD F12, scheduled for Phase 12
    # (Phases.md's Phase 3 line is explicit: "list with pagination, detail, delete").
    query = db.query(Candidate)
    total = query.count()
    candidates = (
        query.order_by(Candidate.created_at.desc(), Candidate.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [CandidateResponse.model_validate(c) for c in candidates]
    return Page.create(items=items, total=total, page=page, page_size=page_size)


def get_candidate_detail(db: Session, candidate_id: int) -> CandidateDetailResponse:
    candidate = (
        db.query(Candidate)
        .options(selectinload(Candidate.candidate_skills))
        .filter(Candidate.id == candidate_id)
        .one_or_none()
    )
    if candidate is None:
        raise NotFoundError(
            "Candidate not found.", code="CANDIDATE_NOT_FOUND", details={"candidate_id": candidate_id}
        )

    # Built explicitly, not via a blind model_validate(candidate): the ORM
    # relationship is named candidate_skills, but the response field is skills —
    # from_attributes matches by name, so it would not populate the field.
    base = CandidateResponse.model_validate(candidate).model_dump()
    return CandidateDetailResponse(**base, skills=_group_skills(candidate.candidate_skills))


def _group_skills(skills: list[CandidateSkill]) -> GroupedSkills:
    grouped = GroupedSkills()
    for skill in skills:
        out = CandidateSkillOut.model_validate(skill)
        getattr(grouped, skill.skill_type.value).append(out)
    return grouped


def get_resume_file(db: Session, candidate_id: int) -> ResumeFile:
    candidate = _get_candidate_or_404(db, candidate_id)
    path = resolve_stored_path(candidate.resume_path)
    if not path.exists():
        raise NotFoundError(
            "Resume file not found on disk.", code="CANDIDATE_NOT_FOUND", details={"candidate_id": candidate_id}
        )
    extension = Path(candidate.resume_path).suffix.lower()
    media_type = _RESUME_CONTENT_TYPES.get(extension, "application/octet-stream")
    return ResumeFile(path=path, media_type=media_type, display_filename=candidate.resume_filename)


def delete_candidate(db: Session, candidate_id: int) -> DeletedResponse:
    candidate = _get_candidate_or_404(db, candidate_id)
    resume_path = candidate.resume_path
    # DB-level cascade (see job_service.delete_job) removes candidate_skills,
    # applications, candidate_scores, and interview_questions for this candidate.
    db.delete(candidate)
    db.commit()
    # File deleted only after the DB commit succeeds. Doing it first would
    # risk a live candidate row pointing at a missing file if the commit
    # then failed — a bare missing file with no row left behind is harmless,
    # a row with no file is not.
    try:
        delete_stored_file(resume_path)
    except OSError:
        logger.warning("Failed to delete stored resume file %s for candidate %s", resume_path, candidate_id)
    return DeletedResponse(id=candidate_id)


def update_application_status(
    db: Session, application_id: int, new_status: ApplicationStatus
) -> Application:
    application = _get_application_or_404(db, application_id)
    application.status = new_status
    db.commit()
    db.refresh(application)
    return application
