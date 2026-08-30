import uuid as uuid_module

from sqlalchemy import ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import QuestionCategory, QuestionDifficulty
from app.database import Base
from app.models.base import CreatedAtMixin, db_enum


class InterviewQuestion(Base, CreatedAtMixin):
    __tablename__ = "interview_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Not explicitly named in Architecture.md 6.2's DELETE /jobs/{id} description
    # (only applications and scores are), but left un-cascaded this FK would
    # orphan rows referencing a deleted job — treated as CASCADE for consistency.
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[QuestionCategory] = mapped_column(db_enum(QuestionCategory), nullable=False)
    difficulty: Mapped[QuestionDifficulty] = mapped_column(
        db_enum(QuestionDifficulty), nullable=False
    )
    rationale: Mapped[str | None] = mapped_column(String(400), nullable=True)
    generation_batch: Mapped[uuid_module.UUID] = mapped_column(Uuid, nullable=False)
    # Grounding-filter outcome, duplicated identically across every row of
    # one generation batch — same denormalized-per-row convention already
    # used for generation_batch above. Persisted (not computed at read
    # time) so GET and a cached "stored, not regenerating" POST show the
    # same partial-result signal a fresh generation call would, not just
    # the moment of generation. requested = the client's count param;
    # generated = what the model returned before filtering; grounded = how
    # many survived the grounding filter, measured before any
    # display-count truncation (interview_service.py Phase 8 fix).
    requested: Mapped[int] = mapped_column(nullable=False)
    generated: Mapped[int] = mapped_column(nullable=False)
    grounded: Mapped[int] = mapped_column(nullable=False)

    candidate: Mapped["Candidate"] = relationship(back_populates="interview_questions")
    job: Mapped["Job"] = relationship(back_populates="interview_questions")
