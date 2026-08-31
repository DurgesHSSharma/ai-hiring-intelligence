"""Analytics dashboard schemas (PRD F10, Architecture.md 6.2 "Analytics",
Phases.md Phase 12). Every response echoes the filters it was computed
under, so a caller never has to guess which `job_id`/date range a given
set of numbers reflects.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from app.core.enums import RiskLevel


class AnalyticsFilters(BaseModel):
    job_id: int | None
    date_from: date | None
    date_to: date | None


class FunnelCounts(BaseModel):
    """F10.1. Each count is applications currently in that status matching
    the filters — a snapshot of `applications.status` today, not a
    cumulative "ever reached this stage" count. `applications` has no
    status-history table, so a cumulative funnel isn't derivable; this is
    stated explicitly rather than implied.
    """

    total: int
    new: int
    shortlisted: int
    interviewed: int
    selected: int
    rejected: int


class OverviewResponse(BaseModel):
    filters: AnalyticsFilters
    funnel: FunnelCounts


class SkillCount(BaseModel):
    skill_name: str
    count: int


class SkillsResponse(BaseModel):
    filters: AnalyticsFilters
    top_candidate_skills: list[SkillCount]
    top_missing_skills: list[SkillCount]


class ScoreBucket(BaseModel):
    range_start: float
    range_end: float
    count: int


class JobAverageScore(BaseModel):
    job_id: int
    job_title: str
    average_fit_score: float
    candidate_count: int


class ScoresResponse(BaseModel):
    filters: AnalyticsFilters
    overall_average_fit_score: float | None
    average_by_job: list[JobAverageScore]
    distribution: list[ScoreBucket]


class RiskLevelCount(BaseModel):
    risk_level: RiskLevel
    count: int


class DepartmentRisk(BaseModel):
    department: str
    average_probability: float
    employee_count: int


class AttritionAnalyticsResponse(BaseModel):
    filters: AnalyticsFilters
    # employees carry no job_id (Architecture.md 5.1 — attrition is a wholly
    # separate subgraph from jobs/candidates/applications), so `job_id` is
    # accepted for contract consistency with the other three analytics
    # endpoints but has no matching column to filter on here. Always false
    # when job_id is None; true whenever a caller supplied one, so this is
    # visible in the response rather than a silent no-op. See
    # analytics_service.py and Memory.md for the full explanation.
    job_id_filter_applied: bool
    total_employees_with_prediction: int
    by_risk_level: list[RiskLevelCount]
    by_department: list[DepartmentRisk]


__all__ = [
    "AnalyticsFilters",
    "AttritionAnalyticsResponse",
    "DepartmentRisk",
    "FunnelCounts",
    "JobAverageScore",
    "OverviewResponse",
    "RiskLevelCount",
    "ScoreBucket",
    "ScoresResponse",
    "SkillCount",
    "SkillsResponse",
]
