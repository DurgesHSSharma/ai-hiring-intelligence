from sqlalchemy import JSON, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ParseStatus
from app.database import Base
from app.models.base import CreatedAtMixin, db_enum


class Candidate(Base, CreatedAtMixin):
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    # Nullable as of Phase 4: email extraction is regex work that belongs to
    # Phase 5's field_extractor.py, not this phase. A row created here (parsed
    # or parse_failed) has no extraction mechanism to populate this column yet,
    # and inventing a placeholder would corrupt Phase 5's dedupe-by-email logic
    # (see Memory.md). No unique constraint exists on this column, so multiple
    # NULLs are schema-safe.
    email: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    resume_path: Mapped[str] = mapped_column(String(500), nullable=False)
    resume_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    resume_text: Mapped[str] = mapped_column(Text, nullable=False)
    education: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Not explicitly marked nullable in Architecture.md 5.2, but it's the ordinal
    # derived from `education`, which is nullable — a row where extraction found
    # no education text cannot have an education_level either. Treated as nullable
    # here; flagged in Memory.md as an inferred fix to what reads like a doc gap.
    education_level: Mapped[int | None] = mapped_column(nullable=True)
    experience_years: Mapped[float | None] = mapped_column(Float, nullable=True)
    projects: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    certifications: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    parse_status: Mapped[ParseStatus] = mapped_column(db_enum(ParseStatus), nullable=False)
    parse_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # passive_deletes=True: see models/job.py — same reasoning, same fix, needed
    # for DELETE /candidates/{id} to actually reach the DB's ondelete="CASCADE"
    # instead of the ORM failing on a NOT NULL FK first.
    applications: Mapped[list["Application"]] = relationship(
        back_populates="candidate", passive_deletes=True
    )
    candidate_skills: Mapped[list["CandidateSkill"]] = relationship(
        back_populates="candidate", passive_deletes=True
    )
    candidate_scores: Mapped[list["CandidateScore"]] = relationship(
        back_populates="candidate", passive_deletes=True
    )
    interview_questions: Mapped[list["InterviewQuestion"]] = relationship(
        back_populates="candidate", passive_deletes=True
    )
