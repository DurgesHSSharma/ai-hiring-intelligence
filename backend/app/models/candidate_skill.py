from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import SkillSource, SkillType
from app.database import Base
from app.models.base import db_enum


class CandidateSkill(Base):
    __tablename__ = "candidate_skills"
    __table_args__ = (
        UniqueConstraint("candidate_id", "skill_name", name="uq_candidate_skills_candidate_skill"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True, nullable=False
    )
    skill_name: Mapped[str] = mapped_column(String(80), nullable=False)
    skill_type: Mapped[SkillType] = mapped_column(db_enum(SkillType), nullable=False)
    source: Mapped[SkillSource] = mapped_column(db_enum(SkillSource), nullable=False)

    candidate: Mapped["Candidate"] = relationship(back_populates="candidate_skills")
