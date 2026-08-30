from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import QuestionCategory, QuestionDifficulty


class GenerateQuestionsRequest(BaseModel):
    job_id: int
    # F8.1: "5-8 questions per candidate." Bounded here so a caller can ask
    # for fewer within that range, but never outside it.
    count: int = Field(default=8, ge=5, le=8)
    regenerate: bool = False


class InterviewQuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    question: str
    category: QuestionCategory
    difficulty: QuestionDifficulty
    rationale: str | None
    generation_batch: UUID
    created_at: datetime


class InterviewQuestionsResponse(BaseModel):
    candidate_id: int
    job_id: int
    generation_batch: UUID
    # Grounding-filter outcome (Phase 8 fix): explicit in the response body
    # rather than left for a caller to infer from len(questions), since a
    # short list looks identical whether the model returned few questions
    # or the grounding filter discarded most of a full set. requested is
    # the count param that was asked for; generated is what the model
    # actually returned before filtering; grounded is how many survived
    # the filter, measured before any display-count truncation; partial
    # is grounded < the 5-question floor.
    requested: int
    generated: int
    grounded: int
    partial: bool
    questions: list[InterviewQuestionOut]
