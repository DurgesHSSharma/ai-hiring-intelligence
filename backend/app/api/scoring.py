from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import CurrentUser, pagination_params
from app.schemas.common import Page
from app.schemas.score import (
    CandidateScoreResponse,
    RankingEntry,
    ScoreJobRequest,
    ScoreJobResponse,
    SkillGapResponse,
)
from app.services import scoring_service

# Two resources (jobs, candidates) share this module, same convention as
# api/candidates.py — no shared prefix, full paths per route.
router = APIRouter(tags=["scoring"])


@router.post("/jobs/{job_id}/score", response_model=ScoreJobResponse)
def score_job(
    job_id: int, payload: ScoreJobRequest, current_user: CurrentUser, db: Session = Depends(get_db)
) -> ScoreJobResponse:
    return scoring_service.score_job(
        db, job_id, candidate_ids=payload.candidate_ids, force=payload.force
    )


@router.get("/jobs/{job_id}/rankings", response_model=Page[RankingEntry])
def get_rankings(
    job_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    pagination: dict = Depends(pagination_params),
) -> Page[RankingEntry]:
    return scoring_service.get_rankings(
        db, job_id, page=pagination["page"], page_size=pagination["page_size"]
    )


@router.get("/candidates/{candidate_id}/score", response_model=CandidateScoreResponse)
def get_candidate_score(
    candidate_id: int, job_id: int, current_user: CurrentUser, db: Session = Depends(get_db)
) -> CandidateScoreResponse:
    return scoring_service.get_candidate_score(db, candidate_id, job_id)


@router.get("/candidates/{candidate_id}/skill-gap", response_model=SkillGapResponse)
def get_skill_gap(
    candidate_id: int, job_id: int, current_user: CurrentUser, db: Session = Depends(get_db)
) -> SkillGapResponse:
    return scoring_service.get_skill_gap(db, candidate_id, job_id)
