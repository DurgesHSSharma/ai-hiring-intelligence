from sqlalchemy import JSON, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import JobSeniority, JobStatus
from app.database import Base
from app.models.base import TimestampMixin, db_enum


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    required_skills: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    min_experience_years: Mapped[float] = mapped_column(Float, nullable=False)
    education_requirement: Mapped[str] = mapped_column(String(80), nullable=False)
    seniority: Mapped[JobSeniority] = mapped_column(db_enum(JobSeniority), nullable=False)
    location: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        db_enum(JobStatus), nullable=False, default=JobStatus.OPEN
    )
    # Audit only (Architecture.md 5.1) — no ownership scoping, and no user-delete
    # endpoint exists, but the FK still needs an explicit ondelete (Rules.md 4.5).
    # SET NULL rather than CASCADE: a job should outlive the user record that
    # created it, which is also why this column must be nullable.
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # passive_deletes=True: without it, SQLAlchemy's unit of work loads these
    # collections on a parent delete and tries to NULL their FK columns itself
    # before issuing the DELETE — which fails outright since those FKs are
    # NOT NULL, and never even reaches the DB's own ondelete="CASCADE". This
    # tells the ORM to trust the database's cascade instead of managing it.
    applications: Mapped[list["Application"]] = relationship(
        back_populates="job", passive_deletes=True
    )
    candidate_scores: Mapped[list["CandidateScore"]] = relationship(
        back_populates="job", passive_deletes=True
    )
    interview_questions: Mapped[list["InterviewQuestion"]] = relationship(
        back_populates="job", passive_deletes=True
    )
