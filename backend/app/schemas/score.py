from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.core.enums import ScoreBand, ScoringMethod, SkillSource


class ScoreJobRequest(BaseModel):
    candidate_ids: list[int] | None = None
    force: bool = False


class ScoreJobResultItem(BaseModel):
    candidate_id: int
    status: Literal["scored", "skipped"]
    final_fit_score: float | None = None
    code: str | None = None
    reason: str | None = None


class ScoreJobResponse(BaseModel):
    job_id: int
    scored: int
    skipped: int
    results: list[ScoreJobResultItem]


class CandidateScoreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    candidate_id: int
    job_id: int
    resume_match_score: float
    skill_match_score: float
    # None when the underlying candidate field (experience_years /
    # education_level) is unknown, not zero — that sub-score is excluded
    # from final_fit_score and the remaining weights are renormalized to
    # sum to 1.0, rather than a fabricated number standing in for "we
    # don't know." excluded_sub_scores names exactly which ones, so the
    # renormalization is visible rather than an implicit fact the caller
    # would have to reverse-engineer from the weights.
    experience_score: float | None
    education_score: float | None
    final_fit_score: float
    band: ScoreBand
    scoring_method: ScoringMethod
    score_version: int
    is_stale: bool
    excluded_sub_scores: list[str]


class RankingEntry(CandidateScoreResponse):
    candidate_name: str | None
    candidate_email: str | None


class SkillGapMatchOut(BaseModel):
    skill: str
    # F4.4 — dictionary (exact) or semantic (partial, embedding-similarity)
    # match. matched_via names the candidate's own skill a semantic match
    # was found against; always None for a dictionary match. Design.md
    # renders these as visually distinct (filled vs. hollow dot) — this is
    # what the frontend switches on to do that.
    source: SkillSource
    matched_via: str | None = None


class SkillGapResponse(BaseModel):
    candidate_id: int
    job_id: int
    matched: list[SkillGapMatchOut]
    missing: list[str]
    additional: list[str]
    percentage: float
