from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import CurrentUser, enforce_interview_generation_rate_limit
from app.schemas.interview import GenerateQuestionsRequest, InterviewQuestionsResponse
from app.services import interview_service

router = APIRouter(tags=["interview"])


@router.post(
    "/candidates/{candidate_id}/interview-questions",
    response_model=InterviewQuestionsResponse,
    dependencies=[Depends(enforce_interview_generation_rate_limit)],
)
def generate_interview_questions(
    candidate_id: int,
    payload: GenerateQuestionsRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> InterviewQuestionsResponse:
    return interview_service.generate_questions(
        db, candidate_id, payload.job_id, count=payload.count, regenerate=payload.regenerate
    )


@router.get("/candidates/{candidate_id}/interview-questions", response_model=InterviewQuestionsResponse)
def get_interview_questions(
    candidate_id: int,
    job_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> InterviewQuestionsResponse:
    return interview_service.get_questions(db, candidate_id, job_id)
