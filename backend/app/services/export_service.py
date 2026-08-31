"""CSV export (PRD F13, Architecture.md 6.2 "Export", Phases.md Phase 12).
Raises domain exceptions from core/exceptions.py; never HTTPException
(Rules.md 5.2).
"""
import csv
import io
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.enums import ApplicationStatus
from app.core.exceptions import NotFoundError
from app.models.application import Application
from app.models.candidate_score import CandidateScore
from app.models.job import Job
from app.services.candidate_service import SortBy, SortOrder, build_candidate_query

_CSV_HEADER = [
    "candidate_id",
    "name",
    "email",
    "fit_score",
    "resume_match_score",
    "skill_match_score",
    "experience_score",
    "education_score",
    "missing_skills",
    "status",
]


@dataclass
class CsvExport:
    """Plain data, not a Starlette response: services/ must not import HTTP
    response classes (Rules.md 4.2) — mirrors candidate_service.ResumeFile.
    api/export.py builds the actual Response from this.
    """

    content: str
    filename: str


def _get_job_or_404(db: Session, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise NotFoundError("Job not found.", code="JOB_NOT_FOUND", details={"job_id": job_id})
    return job


def _rows_to_csv(rows: list[list]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_HEADER)
    writer.writerows(rows)
    return buffer.getvalue()


def export_candidates_csv(
    db: Session,
    job_id: int,
    *,
    search: str | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    skills: list[str] | None = None,
    min_experience: float | None = None,
    education_level: int | None = None,
    status: ApplicationStatus | None = None,
    sort_by: SortBy = "created_at",
    sort_order: SortOrder = "desc",
) -> CsvExport:
    """F13.1/F13.2 — CSV honouring exactly the filters `/candidates` would
    apply for this job, in exactly the same order, because both call the
    identical `build_candidate_query` (candidate_service.py) — a shared
    query builder, not two independently written filter implementations
    that could silently drift apart. No pagination: an export is the
    complete filtered/sorted result set. Row data (fit score and its
    breakdown, missing skills, application status) is fetched with two
    follow-up queries `IN (candidate_ids)`-bounded to exactly the
    already-filtered candidate set from the query above — never the full
    `candidate_scores`/`applications` tables (Phases.md Phase 12: "CSV
    generation must not bypass SQL filtering by fetching the entire table
    first").
    """
    _get_job_or_404(db, job_id)

    query, _ = build_candidate_query(
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
    # No add_columns() call above, so this returns plain Candidate entities
    # in exactly the SQL-determined filter/sort order — the same order the
    # equivalently filtered /candidates call would page through.
    candidates = query.all()
    candidate_ids = [candidate.id for candidate in candidates]

    scores_by_id: dict[int, CandidateScore] = {}
    applications_by_id: dict[int, Application] = {}
    if candidate_ids:
        scores_by_id = {
            score.candidate_id: score
            for score in db.query(CandidateScore)
            .filter(CandidateScore.candidate_id.in_(candidate_ids), CandidateScore.job_id == job_id)
            .all()
        }
        applications_by_id = {
            application.candidate_id: application
            for application in db.query(Application)
            .filter(Application.candidate_id.in_(candidate_ids), Application.job_id == job_id)
            .all()
        }

    rows = []
    for candidate in candidates:
        score = scores_by_id.get(candidate.id)
        application = applications_by_id.get(candidate.id)
        rows.append(
            [
                candidate.id,
                candidate.name or "",
                candidate.email or "",
                score.final_fit_score if score else "",
                score.resume_match_score if score else "",
                score.skill_match_score if score else "",
                score.experience_score if score is not None and score.experience_score is not None else "",
                score.education_score if score is not None and score.education_score is not None else "",
                "; ".join(score.missing_skills) if score else "",
                application.status.value if application else "",
            ]
        )

    return CsvExport(content=_rows_to_csv(rows), filename=f"job_{job_id}_candidates.csv")
