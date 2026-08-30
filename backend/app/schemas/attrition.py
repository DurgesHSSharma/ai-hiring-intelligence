"""Attrition serving schemas (PRD F9.5-F9.9, F11; Phases.md Phase 11).

Three concepts this module keeps deliberately distinct on every response,
per explicit instruction (Memory.md decision 67/70/72):
  1. `probability` - the sigmoid-calibrated probability itself.
  2. `flagged` / `decision_threshold` - the binary operating cutoff (0.2005).
  3. `risk_level` / `risk_level_status` - the three-way display tier. F9.7
     is resolved (Memory.md, 2026-08-30 owner decision): a frozen,
     ranking-derived scheme built from the validated four-seed calibrated
     OOF probability distribution, NOT the original fixed absolute-
     probability bands (<30%/30-60%/>60%), which this supersedes entirely.
     `risk_level` is always one of low/medium/high for a valid prediction -
     never null, never a live percentile against the current employees
     table or a request's own population.
A response never conflates these under one name.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import RiskLevel

MAX_BATCH_SIZE = 500

# Shown on every prediction response - explains what risk_level actually
# means now that F9.7 is resolved, so a caller never has to guess whether
# it's a live rank or a fixed rule. See attrition_service.py.
RISK_LEVEL_TIER_STATUS = (
    "resolved: risk_level is a frozen, ranking-derived tier (owner decision, "
    "2026-08-30) built from the validated four-seed calibrated out-of-fold "
    "probability distribution - not the original PRD F9.7 fixed absolute-"
    "probability bands, and not a live percentile rank against the current "
    "employees table. See GET /attrition/model-info for the exact cutoffs "
    "and derivation, and docs/EVALUATION.md's Phase 10 calibration amendment "
    "for the underlying evidence."
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

    # Always one of low/medium/high for a valid prediction - F9.7 resolved,
    # see this module's docstring and RISK_LEVEL_TIER_STATUS.
    risk_level: RiskLevel
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

    risk_band_status: Literal["resolved"] = "resolved"
    risk_band_note: str = RISK_LEVEL_TIER_STATUS

    # F9.7's frozen, ranking-derived risk-tier scheme - full derivation
    # metadata so a consumer/auditor never has to go read
    # decision_threshold.json directly to understand what risk_level means.
    risk_tier_scheme: str
    risk_tier_high_cutoff: float
    risk_tier_medium_cutoff: float
    risk_tier_percentile_method: str
    risk_tier_oof_seeds: list[int]
    risk_tier_oof_population: int
    risk_tier_derivation_date: str
    risk_tier_known_limitation: str
