from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import RiskLevel
from app.database import Base
from app.models.base import db_enum


class AttritionPrediction(Base):
    __tablename__ = "attrition_predictions"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), index=True, nullable=False
    )
    probability: Mapped[float] = mapped_column(Float, nullable=False)
    # Nullable: PRD F9.7's Low/Medium/High boundaries are not yet approved
    # against calibrated-probability evidence (Memory.md decision 70) -
    # attrition_service.py leaves this unset rather than silently finalizing
    # a band value. See migration 77d9064ae0ac.
    risk_level: Mapped[RiskLevel | None] = mapped_column(db_enum(RiskLevel), nullable=True)
    top_factors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    model_version: Mapped[str] = mapped_column(String(40), nullable=False)
    prediction_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    employee: Mapped["Employee"] = relationship(back_populates="attrition_predictions")
