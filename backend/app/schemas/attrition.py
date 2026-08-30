"""Attrition serving schemas (PRD F9.5-F9.9, F11; Phases.md Phase 11).

Three concepts this module keeps deliberately distinct on every response,
per explicit instruction (Memory.md decision 67/70):
  1. `probability` - the sigmoid-calibrated probability itself.
  2. `flagged` / `decision_threshold` - the binary operating cutoff (0.2005).
  3. `risk_level` / `risk_level_status` - the three-way display band, left
     null and explicitly marked unresolved until PRD F9.7 is approved
     against calibrated evidence (Memory.md decision 70).
A response never conflates these under one name.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import RiskLevel

MAX_BATCH_SIZE = 500

# Shown verbatim wherever risk_level is null - never silently omitted, so a
# caller can't mistake "unresolved" for "no risk". See attrition_service.py.
RISK_LEVEL_UNRESOLVED_STATUS = (
    "unresolved: PRD F9.7's Low/Medium/High boundaries (<30%/30-60%/>60%) have not "
    "been approved by the project owner against calibrated-probability evidence - "
    "the calibrated model's High band is thin (~2% of employees, likely an "
    "undercount given the top-decile calibration limitation). See "
    "docs/EVALUATION.md's Phase 10 calibration amendment and GET /attrition/model-info."
)


class EmployeeFeaturesIn(BaseModel):
    """The 17 canonical business features (data/README.md, Architecture.md
    5.2's `employees` table), each optional so a missing one is reported by
    features.py as INVALID_FEATURE_SET (400) naming the exact field, rather
    than FastAPI's generic 422 before the service layer sees it.

    extra="forbid" is this project's established convention for rejecting
    unrecognised fields outright rather than silently dropping them
    (Memory.md decision 8) - it is also what keeps Gender, MaritalStatus,
    and Over18 (Phase 9's excluded protected attributes) out of every
    request entirely: they are not fields here, so supplying them fails
    request validation before any service or model code runs.
    """

    model_config = ConfigDict(extra="forbid")

    age: int | None = Field(default=None, ge=0)
    distance_from_home: int | None = Field(default=None, ge=0)
    monthly_income: float | None = Field(default=None, ge=0)
    percent_salary_hike: float | None = Field(default=None, ge=0)
    total_working_years: int | None = Field(default=None, ge=0)
    years_at_company: int | None = Field(default=None, ge=0)
    years_since_last_promotion: int | None = Field(default=None, ge=0)
    years_with_curr_manager: int | None = Field(default=None, ge=0)
    job_level: int | None = None
    job_satisfaction: int | None = None
    environment_satisfaction: int | None = None
    relationship_satisfaction: int | None = None
    performance_rating: int | None = None
    stock_option_level: int | None = None
    department: str | None = None
    business_travel: str | None = None
    overtime: bool | None = None


class AttritionPredictRequest(EmployeeFeaturesIn):
    # Optional: when supplied, the prediction is persisted against this
    # employees row (EMPLOYEE_NOT_FOUND if it doesn't exist). When omitted,
    # this is an ad-hoc "enter a hypothetical profile" prediction (PRD's
    # "enter or select employee record" flow) and nothing is persisted.
    employee_id: int | None = None


class AttritionBatchPredictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    records: list[AttritionPredictRequest] = Field(min_length=1, max_length=MAX_BATCH_SIZE)


class TopFactorOut(BaseModel):
    feature: str
    contribution: float


class AttritionPredictResponse(BaseModel):
    employee_id: int | None
    prediction_id: int | None = None

    # The calibrated probability - see this module's own docstring. Never
    # the raw SMOTE classifier output (Memory.md decision 69).
    probability: float
    flagged: bool
    decision_threshold: float
    calibration_method: str
    model_family: str
    imbalance_strategy: str
    model_version: str

    top_factors: list[TopFactorOut]

    risk_level: RiskLevel | None
    risk_level_status: str

    calibration_known_limitation: str


class AttritionBatchResultItem(BaseModel):
    index: int
    employee_id: int | None
    status: Literal["predicted", "failed"]
    prediction: AttritionPredictResponse | None = None
    code: str | None = None
    reason: str | None = None


class AttritionBatchPredictResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    results: list[AttritionBatchResultItem]


class LatestPredictionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    probability: float
    risk_level: RiskLevel | None
    model_version: str
    prediction_date: datetime


class EmployeeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    age: int
    department: str
    job_level: int
    monthly_income: float
    years_at_company: int
    years_since_last_promotion: int
    years_with_curr_manager: int
    total_working_years: int
    job_satisfaction: int
    environment_satisfaction: int
    relationship_satisfaction: int
    performance_rating: int
    overtime: bool
    business_travel: str
    distance_from_home: int
    percent_salary_hike: float
    stock_option_level: int
    latest_prediction: LatestPredictionOut | None = None


class ModelInfoResponse(BaseModel):
    model_family: str
    imbalance_strategy: str
    calibration_method: str
    calibrated_decision_threshold: float
    model_version: str
    feature_names: list[str]

    raw_evaluation_threshold: float
    raw_evaluation_metrics: dict
    calibrated_evaluation_metrics: dict
    calibration_brier_improvement_mean: float | None = None
    calibration_brier_improvement_std: float | None = None
    calibration_known_limitation: str

    risk_band_status: Literal["unresolved"] = "unresolved"
    risk_band_note: str = RISK_LEVEL_UNRESOLVED_STATUS
