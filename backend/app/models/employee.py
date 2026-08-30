from sqlalchemy import Boolean, Float, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    age: Mapped[int] = mapped_column(nullable=False)
    department: Mapped[str] = mapped_column(String(80), nullable=False)
    job_level: Mapped[int] = mapped_column(nullable=False)
    monthly_income: Mapped[float] = mapped_column(Float, nullable=False)
    years_at_company: Mapped[int] = mapped_column(nullable=False)
    years_since_last_promotion: Mapped[int] = mapped_column(nullable=False)
    years_with_curr_manager: Mapped[int] = mapped_column(nullable=False)
    total_working_years: Mapped[int] = mapped_column(nullable=False)
    job_satisfaction: Mapped[int] = mapped_column(nullable=False)
    environment_satisfaction: Mapped[int] = mapped_column(nullable=False)
    relationship_satisfaction: Mapped[int] = mapped_column(nullable=False)
    performance_rating: Mapped[int] = mapped_column(nullable=False)
    overtime: Mapped[bool] = mapped_column(Boolean, nullable=False)
    business_travel: Mapped[str] = mapped_column(String(40), nullable=False)
    distance_from_home: Mapped[int] = mapped_column(nullable=False)
    percent_salary_hike: Mapped[float] = mapped_column(Float, nullable=False)
    stock_option_level: Mapped[int] = mapped_column(nullable=False)
    # Nullable — label, historical rows only (Architecture.md 5.2).
    attrition: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # passive_deletes=True: see models/job.py — same reasoning, same fix, needed
    # for an employee delete to actually reach the DB's ondelete="CASCADE"
    # instead of the ORM failing on a NOT NULL FK first.
    attrition_predictions: Mapped[list["AttritionPrediction"]] = relationship(
        back_populates="employee", passive_deletes=True
    )
