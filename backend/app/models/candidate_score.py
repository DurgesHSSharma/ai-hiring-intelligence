from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ScoringMethod
from app.database import Base
from app.models.base import CreatedAtMixin, db_enum


class CandidateScore(Base, CreatedAtMixin):
    __tablename__ = "candidate_scores"
    __table_args__ = (
        UniqueConstraint("candidate_id", "job_id", name="uq_candidate_scores_candidate_job"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True, nullable=False
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    resume_match_score: Mapped[float] = mapped_column(Float, nullable=False)
    skill_match_score: Mapped[float] = mapped_column(Float, nullable=False)
    # Nullable as of Phase 6: a candidate with no extracted experience_years/
    # education_level has no computable sub-score at all, not a zero one —
    # scoring_service excludes a null sub-score from the composite and
    # renormalizes the remaining weights, rather than fabricating a floor
    # value that would be indistinguishable from a genuine low score
    # (see Memory.md).
    experience_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    education_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_fit_score: Mapped[float] = mapped_column(Float, index=True, nullable=False)
    matched_skills: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    missing_skills: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    additional_skills: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    scoring_method: Mapped[ScoringMethod] = mapped_column(db_enum(ScoringMethod), nullable=False)
    score_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    candidate: Mapped["Candidate"] = relationship(back_populates="candidate_scores")
    job: Mapped["Job"] = relationship(back_populates="candidate_scores")
