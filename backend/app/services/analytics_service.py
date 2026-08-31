"""Analytics dashboard aggregation (PRD F10, Architecture.md 6.2
"Analytics", Phases.md Phase 12). Raises domain exceptions from
core/exceptions.py; never HTTPException (Rules.md 5.2).

Binding constraint for every function here (Phases.md Phase 12 acceptance):
filtering, grouping, and aggregation happen in SQL. Python only reshapes an
already-aggregated, at-most-a-few-dozen-row result into the response schema
(e.g. filling a fixed set of score buckets or risk levels that SQL's GROUP
BY did not happen to return a row for) — it never filters, sorts, or
aggregates the underlying candidates/employees/scores population itself.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone

from sqlalchemy import Integer, case, cast, func, text
from sqlalchemy.orm import Session

from app.core.enums import ApplicationStatus, RiskLevel
from app.models.application import Application
from app.models.attrition_prediction import AttritionPrediction
from app.models.candidate import Candidate
from app.models.candidate_score import CandidateScore
from app.models.candidate_skill import CandidateSkill
from app.models.employee import Employee
from app.models.job import Job
from app.schemas.analytics import (
    AnalyticsFilters,
    AttritionAnalyticsResponse,
    DepartmentRisk,
    FunnelCounts,
    JobAverageScore,
    OverviewResponse,
    RiskLevelCount,
    ScoreBucket,
    ScoresResponse,
    SkillCount,
    SkillsResponse,
)

# F10.2 — "most common" / "most frequently missing" imply a ranked top-N,
# not the full skill vocabulary. 10 matches the page_size default used
# everywhere else pagination applies (dependencies.py).
TOP_SKILLS_LIMIT = 10

_BUCKET_WIDTH = 10
_BUCKET_STARTS = list(range(0, 100, _BUCKET_WIDTH))


def _day_start(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


def _day_end(d: date) -> datetime:
    return datetime.combine(d, time.max, tzinfo=timezone.utc)


def _apply_date_range(query, column, *, date_from: date | None, date_to: date | None):
    if date_from is not None:
        query = query.filter(column >= _day_start(date_from))
    if date_to is not None:
        query = query.filter(column <= _day_end(date_to))
    return query


def _filters(job_id: int | None, date_from: date | None, date_to: date | None) -> AnalyticsFilters:
    return AnalyticsFilters(job_id=job_id, date_from=date_from, date_to=date_to)


def get_overview(
    db: Session, *, job_id: int | None, date_from: date | None, date_to: date | None
) -> OverviewResponse:
    """F10.1 — current `applications.status` distribution matching the
    filters. A snapshot of where every application sits today, not a
    cumulative "ever passed through this stage" funnel: `applications` has
    no status-history table, so a cumulative count isn't derivable from
    this schema and this endpoint does not claim to produce one.
    """
    query = db.query(Application.status, func.count(Application.id))
    if job_id is not None:
        query = query.filter(Application.job_id == job_id)
    query = _apply_date_range(query, Application.created_at, date_from=date_from, date_to=date_to)
    rows = query.group_by(Application.status).all()

    counts = {status: 0 for status in ApplicationStatus}
    for status, count in rows:
        counts[status] = count

    funnel = FunnelCounts(
        total=sum(counts.values()),
        new=counts[ApplicationStatus.NEW],
        shortlisted=counts[ApplicationStatus.SHORTLISTED],
        interviewed=counts[ApplicationStatus.INTERVIEWED],
        selected=counts[ApplicationStatus.SELECTED],
        rejected=counts[ApplicationStatus.REJECTED],
    )
    return OverviewResponse(filters=_filters(job_id, date_from, date_to), funnel=funnel)


def _top_candidate_skills(
    db: Session, *, job_id: int | None, date_from: date | None, date_to: date | None
) -> list[SkillCount]:
    query = db.query(CandidateSkill.skill_name, func.count(CandidateSkill.id)).join(
        Candidate, Candidate.id == CandidateSkill.candidate_id
    )
    if job_id is not None:
        query = query.join(Application, Application.candidate_id == Candidate.id).filter(
            Application.job_id == job_id
        )
    query = _apply_date_range(query, Candidate.created_at, date_from=date_from, date_to=date_to)
    rows = (
        query.group_by(CandidateSkill.skill_name)
        .order_by(func.count(CandidateSkill.id).desc(), CandidateSkill.skill_name.asc())
        .limit(TOP_SKILLS_LIMIT)
        .all()
    )
    return [SkillCount(skill_name=name, count=count) for name, count in rows]


def _top_missing_skills(
    db: Session, *, job_id: int | None, date_from: date | None, date_to: date | None
) -> list[SkillCount]:
    """`candidate_scores.missing_skills` is a JSON array column (Rules.md
    4.5 has no portable Core construct for unnesting one), so this is the
    one query in the service that drops to `text()` rather than the ORM —
    still one SQL statement doing the grouping/counting/limiting itself,
    never a Python loop over fetched rows. SQLite's `json_each` and
    PostgreSQL's `json_array_elements_text` are the dialect-appropriate
    equivalents of the same operation (`database.py` already branches on
    dialect for the SQLite foreign-key pragma — same precedent).
    """
    conditions = ["candidate_scores.missing_skills != '[]'"]
    params: dict[str, object] = {"limit": TOP_SKILLS_LIMIT}
    if job_id is not None:
        conditions.append("candidate_scores.job_id = :job_id")
        params["job_id"] = job_id
    if date_from is not None:
        conditions.append("candidate_scores.created_at >= :date_from")
        params["date_from"] = _day_start(date_from)
    if date_to is not None:
        conditions.append("candidate_scores.created_at <= :date_to")
        params["date_to"] = _day_end(date_to)
    where_clause = "WHERE " + " AND ".join(conditions)

    dialect = db.get_bind().dialect.name
    if dialect == "sqlite":
        unnest = "json_each(candidate_scores.missing_skills) AS je"
        skill_column = "je.value"
    else:
        unnest = "json_array_elements_text(candidate_scores.missing_skills) AS je(value)"
        skill_column = "je.value"

    sql = text(
        f"""
        SELECT {skill_column} AS skill_name, COUNT(*) AS skill_count
        FROM candidate_scores, {unnest}
        {where_clause}
        GROUP BY {skill_column}
        ORDER BY skill_count DESC, skill_name ASC
        LIMIT :limit
        """
    )
    rows = db.execute(sql, params).all()
    return [SkillCount(skill_name=row.skill_name, count=row.skill_count) for row in rows]


def get_skills(
    db: Session, *, job_id: int | None, date_from: date | None, date_to: date | None
) -> SkillsResponse:
    """F10.2 — most common candidate skills (from `candidate_skills`, the
    normalized per-candidate skill table) and most frequently missing
    skills across the pipeline (from `candidate_scores.missing_skills`,
    populated per scoring run — see scoring_service.py).
    """
    return SkillsResponse(
        filters=_filters(job_id, date_from, date_to),
        top_candidate_skills=_top_candidate_skills(db, job_id=job_id, date_from=date_from, date_to=date_to),
        top_missing_skills=_top_missing_skills(db, job_id=job_id, date_from=date_from, date_to=date_to),
    )


def get_scores(
    db: Session, *, job_id: int | None, date_from: date | None, date_to: date | None
) -> ScoresResponse:
    """F10.3 — average fit score per job and a score distribution
    histogram, both computed by the database. The bucket boundary is a SQL
    `CASE`/integer-cast expression (portable across SQLite and PostgreSQL),
    not a Python bucketing loop over fetched rows — the only Python step is
    filling in a fixed, always-10-bucket list from whatever (at most 10)
    grouped rows SQL returned, so an empty bucket reads as `count: 0`
    rather than being silently absent.
    """
    overall_query = db.query(func.avg(CandidateScore.final_fit_score))
    if job_id is not None:
        overall_query = overall_query.filter(CandidateScore.job_id == job_id)
    overall_query = _apply_date_range(
        overall_query, CandidateScore.created_at, date_from=date_from, date_to=date_to
    )
    overall_average = overall_query.scalar()

    by_job_query = db.query(
        Job.id, Job.title, func.avg(CandidateScore.final_fit_score), func.count(CandidateScore.id)
    ).join(CandidateScore, CandidateScore.job_id == Job.id)
    if job_id is not None:
        by_job_query = by_job_query.filter(Job.id == job_id)
    by_job_query = _apply_date_range(
        by_job_query, CandidateScore.created_at, date_from=date_from, date_to=date_to
    )
    by_job_rows = by_job_query.group_by(Job.id, Job.title).order_by(Job.id.asc()).all()
    average_by_job = [
        JobAverageScore(job_id=jid, job_title=title, average_fit_score=round(avg, 1), candidate_count=count)
        for jid, title, avg, count in by_job_rows
    ]

    # Non-negative scores (0-100 by construction), so integer division
    # truncation is equivalent to floor(); the >=100 case is folded into
    # the 90-100 bucket explicitly rather than spilling into a nonexistent
    # 11th bucket.
    bucket_expr = case(
        (CandidateScore.final_fit_score >= 100, _BUCKET_STARTS[-1]),
        else_=cast(CandidateScore.final_fit_score / _BUCKET_WIDTH, Integer) * _BUCKET_WIDTH,
    )
    dist_query = db.query(bucket_expr, func.count(CandidateScore.id))
    if job_id is not None:
        dist_query = dist_query.filter(CandidateScore.job_id == job_id)
    dist_query = _apply_date_range(dist_query, CandidateScore.created_at, date_from=date_from, date_to=date_to)
    dist_rows = dist_query.group_by(bucket_expr).all()
    counts_by_bucket = {int(bucket): count for bucket, count in dist_rows}
    distribution = [
        ScoreBucket(range_start=start, range_end=start + _BUCKET_WIDTH, count=counts_by_bucket.get(start, 0))
        for start in _BUCKET_STARTS
    ]

    return ScoresResponse(
        filters=_filters(job_id, date_from, date_to),
        overall_average_fit_score=round(overall_average, 1) if overall_average is not None else None,
        average_by_job=average_by_job,
        distribution=distribution,
    )


def get_attrition_analytics(
    db: Session, *, job_id: int | None, date_from: date | None, date_to: date | None
) -> AttritionAnalyticsResponse:
    """F10.4 — count by risk tier and average risk by department, computed
    directly from the persisted `attrition_predictions.risk_level`/
    `probability` columns (Phases.md Phase 12: never re-invoke predictor.py
    per employee just to total up already-computed tiers). Only each
    employee's own latest prediction counts — the same "latest per
    employee" subquery shape attrition_service.list_employees() already
    uses, scoped to whatever date range is given so the aggregate reflects
    predictions made in that window.

    `job_id` is accepted, per the documented analytics contract shared by
    all four endpoints, but employees carry no relationship to jobs
    anywhere in the schema (Architecture.md 5.1) — there is no column to
    filter on. It has no effect here; `job_id_filter_applied` on the
    response says so explicitly rather than silently ignoring it. Flagged
    to the project owner in this phase's report as a documented, not
    silent, interpretation — see Memory.md.
    """
    latest_subq = (
        db.query(
            AttritionPrediction.employee_id.label("employee_id"),
            func.max(AttritionPrediction.prediction_date).label("latest_date"),
        )
    )
    latest_subq = _apply_date_range(
        latest_subq, AttritionPrediction.prediction_date, date_from=date_from, date_to=date_to
    )
    latest_subq = latest_subq.group_by(AttritionPrediction.employee_id).subquery()

    def _join_latest(query):
        return query.join(
            latest_subq,
            (AttritionPrediction.employee_id == latest_subq.c.employee_id)
            & (AttritionPrediction.prediction_date == latest_subq.c.latest_date),
        )

    total_employees = db.query(func.count()).select_from(latest_subq).scalar() or 0

    by_risk_rows = _join_latest(
        db.query(AttritionPrediction.risk_level, func.count(AttritionPrediction.id))
    ).group_by(AttritionPrediction.risk_level).all()
    counts_by_level = {level: 0 for level in RiskLevel}
    for level, count in by_risk_rows:
        # None here means a prediction persisted before F9.7 resolved
        # risk_level (Memory.md decision 72) — a real, historical gap, not
        # a bug, and deliberately excluded from the by-tier breakdown
        # rather than invented a tier for.
        if level is not None:
            counts_by_level[level] = count

    by_department_rows = (
        _join_latest(
            db.query(
                Employee.department,
                func.avg(AttritionPrediction.probability),
                func.count(AttritionPrediction.id),
            ).join(Employee, Employee.id == AttritionPrediction.employee_id)
        )
        .group_by(Employee.department)
        .order_by(Employee.department.asc())
        .all()
    )
    by_department = [
        DepartmentRisk(department=dept, average_probability=round(avg, 4), employee_count=count)
        for dept, avg, count in by_department_rows
    ]

    filters = _filters(job_id, date_from, date_to)
    return AttritionAnalyticsResponse(
        filters=filters,
        job_id_filter_applied=job_id is not None,
        total_employees_with_prediction=total_employees,
        by_risk_level=[RiskLevelCount(risk_level=level, count=counts_by_level[level]) for level in RiskLevel],
        by_department=by_department,
    )
