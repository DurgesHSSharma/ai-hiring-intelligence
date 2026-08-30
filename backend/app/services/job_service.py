"""Job CRUD, aggregate detail, and stale-marking on edit. Raises domain
exceptions from core/exceptions.py; never HTTPException (Rules.md 5.2).
"""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.enums import JobStatus
from app.core.exceptions import NotFoundError
from app.ml.skills.skill_matcher import match_skills
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.candidate_score import CandidateScore
from app.models.job import Job
from app.models.user import User
from app.schemas.common import DeletedResponse, Page
from app.schemas.job import (
    JobCreate,
    JobDetailResponse,
    JobResponse,
    JobTopCandidate,
    JobUpdate,
    SuggestedSkill,
    SuggestedSkillsResponse,
)


def _get_job_or_404(db: Session, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise NotFoundError("Job not found.", code="JOB_NOT_FOUND", details={"job_id": job_id})
    return job


def create_job(db: Session, payload: JobCreate, current_user: User) -> Job:
    job = Job(**payload.model_dump(), created_by=current_user.id)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def list_jobs(
    db: Session, *, search: str | None, status_filter: str, page: int, page_size: int
) -> Page[JobResponse]:
    query = db.query(Job)
    if status_filter != "all":
        query = query.filter(Job.status == JobStatus(status_filter))
    if search:
        query = query.filter(Job.title.ilike(f"%{search}%"))

    total = query.count()
    jobs = (
        query.order_by(Job.created_at.desc(), Job.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [JobResponse.model_validate(job) for job in jobs]
    return Page.create(items=items, total=total, page=page, page_size=page_size)


def get_job_detail(db: Session, job_id: int) -> JobDetailResponse:
    job = _get_job_or_404(db, job_id)

    candidate_count = (
        db.query(func.count(Application.id)).filter(Application.job_id == job_id).scalar()
    )
    # SQL AVG over zero rows is NULL, which .scalar() hands back as None directly —
    # never coerced to 0.0. A job with no candidates has no average score, not a
    # zero one; the frontend must be able to tell "no data" from "scored zero."
    average_fit_score = (
        db.query(func.avg(CandidateScore.final_fit_score))
        .filter(CandidateScore.job_id == job_id)
        .scalar()
    )

    top_candidate = None
    top_score = (
        db.query(CandidateScore)
        .filter(CandidateScore.job_id == job_id)
        .order_by(CandidateScore.final_fit_score.desc())
        .first()
    )
    if top_score is not None:
        candidate = db.get(Candidate, top_score.candidate_id)
        top_candidate = JobTopCandidate(
            candidate_id=top_score.candidate_id,
            name=candidate.name if candidate else None,
            final_fit_score=top_score.final_fit_score,
        )

    base = JobResponse.model_validate(job).model_dump()
    return JobDetailResponse(
        **base,
        candidate_count=candidate_count,
        average_fit_score=average_fit_score,
        top_candidate=top_candidate,
    )


def update_job(db: Session, job_id: int, payload: JobUpdate) -> Job:
    job = _get_job_or_404(db, job_id)
    changes = payload.model_dump(exclude_unset=True)

    # Only description and required_skills feed scoring (PRD F2.4) — every other
    # field (title, location, seniority, education_requirement, min_experience_years,
    # status) is excluded on purpose. Compared by value, not by key presence, so
    # resending an unchanged value is a no-op; required_skills compares as a set so
    # a reorder alone doesn't count as a change.
    marks_stale = (
        "description" in changes and changes["description"] != job.description
    ) or (
        "required_skills" in changes
        and set(changes["required_skills"]) != set(job.required_skills)
    )

    for field, value in changes.items():
        setattr(job, field, value)

    if marks_stale:
        db.query(CandidateScore).filter(CandidateScore.job_id == job_id).update(
            {"is_stale": True}
        )

    db.commit()
    db.refresh(job)
    return job


def get_suggested_skills(db: Session, job_id: int) -> SuggestedSkillsResponse:
    """Read-only (PRD F4.5, Rules.md-consistent with the project owner's
    explicit correction against silently mutating required_skills — see
    schemas/job.py's SuggestedSkillsResponse docstring). Runs the same
    dictionary matcher used on resumes against the job description, and
    excludes anything the recruiter already listed (case-insensitively —
    a recruiter typing "python" shouldn't be re-suggested "Python").
    """
    job = _get_job_or_404(db, job_id)
    already_listed = {skill.lower() for skill in job.required_skills}
    suggested = [
        SuggestedSkill(canonical=match.canonical, type=match.skill_type)
        for match in match_skills(job.description)
        if match.canonical.lower() not in already_listed
    ]
    return SuggestedSkillsResponse(job_id=job_id, suggested=suggested)


def delete_job(db: Session, job_id: int) -> DeletedResponse:
    job = _get_job_or_404(db, job_id)
    # No ORM-level cascade= on any relationship (deliberate, from Phase 2) — this
    # single DELETE relies entirely on the DB-level ondelete="CASCADE" FKs plus
    # SQLite's PRAGMA foreign_keys=ON to remove applications/scores/questions.
    db.delete(job)
    db.commit()
    return DeletedResponse(id=job_id)
