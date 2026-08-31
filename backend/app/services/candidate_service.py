"""Candidate read/delete, application status updates, and the F12
filter/search/sort query builder. Raises domain exceptions from
core/exceptions.py; never HTTPException (Rules.md 5.2).
"""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy import Subquery, func, or_
from sqlalchemy.orm import Query, Session, selectinload

from app.core.enums import ApplicationStatus
from app.core.exceptions import NotFoundError
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.candidate_score import CandidateScore
from app.models.candidate_skill import CandidateSkill
from app.schemas.candidate import (
    CandidateDetailResponse,
    CandidateListItem,
    CandidateResponse,
    CandidateSkillOut,
    GroupedSkills,
)
from app.schemas.common import DeletedResponse, Page
from app.utils.files import delete_stored_file, resolve_stored_path

logger = logging.getLogger(__name__)

SortBy = Literal["fit_score", "experience", "created_at", "name"]
SortOrder = Literal["asc", "desc"]

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


def build_candidate_query(
    db: Session,
    *,
    job_id: int | None = None,
    search: str | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    skills: list[str] | None = None,
    min_experience: float | None = None,
    education_level: int | None = None,
    status: ApplicationStatus | None = None,
    sort_by: SortBy = "created_at",
    sort_order: SortOrder = "desc",
) -> tuple[Query, Subquery]:
    """F12's full filter/search/sort surface (Architecture.md 6.2's
    `/candidates` query parameters), built entirely as one SQL query — every
    `.filter()` call below becomes a SQL `AND` condition on the same query
    (Phases.md Phase 12: "combined filters behave as AND"), never a Python
    post-filter over a fetched list. Shared by candidate_service.list_candidates
    (paginated) and export_service.export_candidates_csv (unpaginated, same
    filters) so the two can never silently drift apart — Phase 12's CSV
    acceptance criterion is that the export exactly matches the equivalently
    filtered `/candidates` result.

    Returns `(query, score_subquery)` — the score subquery is always joined
    in (not only when a score filter/sort is requested) so a caller can
    always read `score_subquery.c.best_score` for display, e.g.
    `CandidateListItem.fit_score`.
    """
    query = db.query(Candidate)

    # job_id restricts to candidates with an Application to that job. Safe
    # as a plain INNER JOIN (never duplicates a candidate row): applications
    # has a unique constraint on (candidate_id, job_id), so at most one row
    # matches per candidate once job_id is fixed.
    if job_id is not None:
        query = query.join(Application, Application.candidate_id == Candidate.id).filter(
            Application.job_id == job_id
        )
        if status is not None:
            query = query.filter(Application.status == status)
    elif status is not None:
        # No job_id: a candidate can have several applications, so an
        # unscoped join could return the same candidate once per matching
        # application. .any() compiles to a correlated EXISTS instead —
        # filters correctly with no risk of duplicate rows.
        query = query.filter(Candidate.applications.any(Application.status == status))

    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                Candidate.name.ilike(like),
                Candidate.email.ilike(like),
                Candidate.candidate_skills.any(CandidateSkill.skill_name.ilike(like)),
            )
        )

    # AND semantics across repeated `skills` values: each one is its own
    # .filter() call (its own EXISTS), so a candidate must match every
    # listed skill, not any one of them — required for F12.3.
    for skill in skills or []:
        query = query.filter(
            Candidate.candidate_skills.any(func.lower(CandidateSkill.skill_name) == skill.lower())
        )

    if min_experience is not None:
        # NULL (unknown) experience is excluded, not treated as passing —
        # same "unknown is not zero" convention scoring_service.py already
        # applies to this column.
        query = query.filter(
            Candidate.experience_years.isnot(None), Candidate.experience_years >= min_experience
        )

    if education_level is not None:
        query = query.filter(Candidate.education_level == education_level)

    # Best (highest) score per candidate, scoped to job_id when given —
    # always joined so fit_score is always readable, not only when
    # filtering/sorting on it.
    score_query = db.query(
        CandidateScore.candidate_id.label("candidate_id"),
        func.max(CandidateScore.final_fit_score).label("best_score"),
    )
    if job_id is not None:
        score_query = score_query.filter(CandidateScore.job_id == job_id)
    score_subq = score_query.group_by(CandidateScore.candidate_id).subquery()
    query = query.outerjoin(score_subq, score_subq.c.candidate_id == Candidate.id)

    if min_score is not None:
        query = query.filter(score_subq.c.best_score.isnot(None), score_subq.c.best_score >= min_score)
    if max_score is not None:
        query = query.filter(score_subq.c.best_score.isnot(None), score_subq.c.best_score <= max_score)

    query = _apply_candidate_sort(query, score_subq, sort_by=sort_by, sort_order=sort_order)
    return query, score_subq


def _apply_candidate_sort(query: Query, score_subq: Subquery, *, sort_by: SortBy, sort_order: SortOrder) -> Query:
    columns: dict[SortBy, object] = {
        "fit_score": score_subq.c.best_score,
        "experience": Candidate.experience_years,
        "created_at": Candidate.created_at,
        "name": Candidate.name,
    }
    column = columns[sort_by]
    primary = column.desc() if sort_order == "desc" else column.asc()
    # NULLs sort last regardless of direction (portable — SQLAlchemy compiles
    # nullslast() per-dialect) and Candidate.id.asc() is the deterministic
    # tie-breaker for equal values, the same secondary-key convention
    # scoring_service.get_rankings() already uses (Phases.md Phase 12:
    # "sorting is stable and correct in both directions").
    return query.order_by(primary.nullslast(), Candidate.id.asc())


def list_candidates(
    db: Session,
    *,
    job_id: int | None = None,
    search: str | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    skills: list[str] | None = None,
    min_experience: float | None = None,
    education_level: int | None = None,
    status: ApplicationStatus | None = None,
    sort_by: SortBy = "created_at",
    sort_order: SortOrder = "desc",
    page: int,
    page_size: int,
) -> Page[CandidateListItem]:
    query, score_subq = build_candidate_query(
        db,
        job_id=job_id,
        search=search,
        min_score=min_score,
        max_score=max_score,
        skills=skills,
        min_experience=min_experience,
        education_level=education_level,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    total = query.count()
    rows = (
        query.add_columns(score_subq.c.best_score)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [
        CandidateListItem(**CandidateResponse.model_validate(candidate).model_dump(), fit_score=fit_score)
        for candidate, fit_score in rows
    ]
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
