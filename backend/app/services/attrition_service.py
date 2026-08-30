"""Attrition prediction service layer (PRD F9/F11, Architecture.md 7.4,
Phases.md Phase 11). Raises domain exceptions from core/exceptions.py;
never HTTPException (Rules.md 5.2).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.enums import RiskLevel
from app.core.exceptions import AppError, NotFoundError
from app.ml.attrition import features, predictor
from app.models.attrition_prediction import AttritionPrediction
from app.models.employee import Employee
from app.schemas.attrition import (
    RISK_LEVEL_UNRESOLVED_STATUS,
    AttritionBatchPredictRequest,
    AttritionBatchPredictResponse,
    AttritionBatchResultItem,
    AttritionPredictRequest,
    AttritionPredictResponse,
    EmployeeOut,
    LatestPredictionOut,
    ModelInfoResponse,
    TopFactorOut,
)
from app.schemas.common import Page

# F9.7's boundaries - configurable, deliberately NOT applied (see
# RISK_BAND_RESOLVED below). Kept here rather than inline so a future
# owner-approved value change is a one-line edit, not a code restructure.
RISK_BAND_LOW_MAX = 0.30
RISK_BAND_HIGH_MIN = 0.60

# Mirrors app/ml/skills/skill_gap.py's THRESHOLD_VALIDATED gate (Phase 7): a
# contentious constant is coded and ready, but refuses to activate until a
# named authority signs off. Here: PRD F9.7's fixed bands, checked against
# calibrated-probability evidence and found thin / likely-undercounting in
# the High band (Memory.md decision 70) - a product decision for the
# project owner, not something engineering resolves by shipping anyway.
# Flip only after that explicit approval; until then _compute_risk_band()
# always returns None, and every response says so via
# RISK_LEVEL_UNRESOLVED_STATUS rather than silently omitting the field.
RISK_BAND_RESOLVED = False


def _compute_risk_band(probability: float) -> RiskLevel | None:
    """Isolated, pluggable F9.7 risk band. Returns None unconditionally
    while RISK_BAND_RESOLVED is False (Phases.md Phase 11: "do not silently
    apply the existing bands and present them as finalized") - the boundary
    logic below is ready to use the moment that flips, with no other file
    needing to change.
    """
    if not RISK_BAND_RESOLVED:
        return None
    if probability < RISK_BAND_LOW_MAX:
        return RiskLevel.LOW
    if probability > RISK_BAND_HIGH_MIN:
        return RiskLevel.HIGH
    return RiskLevel.MEDIUM


def _get_employee_or_404(db: Session, employee_id: int) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise NotFoundError(
            "Employee not found.", code="EMPLOYEE_NOT_FOUND", details={"employee_id": employee_id}
        )
    return employee


def _run_prediction(payload: AttritionPredictRequest) -> tuple[float, bool, list[dict], RiskLevel | None]:
    artifacts = predictor.get_artifacts()
    feature_row = features.build_feature_row(payload, artifacts.feature_names)
    probability = predictor.predict_proba(feature_row)
    flagged = probability >= artifacts.calibrated_threshold
    factors = predictor.top_factors(feature_row)
    risk_level = _compute_risk_band(probability)
    return probability, flagged, factors, risk_level


def _to_response(
    *,
    employee_id: int | None,
    probability: float,
    flagged: bool,
    factors: list[dict],
    risk_level: RiskLevel | None,
    prediction_id: int | None,
) -> AttritionPredictResponse:
    artifacts = predictor.get_artifacts()
    return AttritionPredictResponse(
        employee_id=employee_id,
        prediction_id=prediction_id,
        probability=round(probability, 4),
        flagged=flagged,
        decision_threshold=artifacts.calibrated_threshold,
        calibration_method=artifacts.calibration_method,
        model_family=predictor.MODEL_FAMILY,
        imbalance_strategy=predictor.IMBALANCE_STRATEGY,
        model_version=artifacts.model_version,
        top_factors=[TopFactorOut(**f) for f in factors],
        risk_level=risk_level,
        risk_level_status=RISK_LEVEL_UNRESOLVED_STATUS,
        calibration_known_limitation=artifacts.calibration_known_limitation,
    )


def _persist(db: Session, employee_id: int, probability: float, risk_level: RiskLevel | None, factors: list[dict]) -> int:
    row = AttritionPrediction(
        employee_id=employee_id,
        probability=probability,
        risk_level=risk_level,
        top_factors=factors,
        model_version=predictor.get_artifacts().model_version,
        prediction_date=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id


def predict(db: Session, payload: AttritionPredictRequest) -> AttritionPredictResponse:
    if payload.employee_id is not None:
        _get_employee_or_404(db, payload.employee_id)

    probability, flagged, factors, risk_level = _run_prediction(payload)

    prediction_id = None
    if payload.employee_id is not None:
        prediction_id = _persist(db, payload.employee_id, probability, risk_level, factors)

    return _to_response(
        employee_id=payload.employee_id,
        probability=probability,
        flagged=flagged,
        factors=factors,
        risk_level=risk_level,
        prediction_id=prediction_id,
    )


def predict_batch(db: Session, payload: AttritionBatchPredictRequest) -> AttritionBatchPredictResponse:
    # Checked once, up front: a missing model fails the whole batch loudly
    # (503 ATTRITION_MODEL_MISSING) rather than recording every record as an
    # individually failed item - mirrors scoring_service.score_job's
    # embedding-model-unavailable precedent.
    predictor.get_artifacts()

    results: list[AttritionBatchResultItem] = []
    succeeded = 0
    for index, record in enumerate(payload.records):
        try:
            if record.employee_id is not None:
                _get_employee_or_404(db, record.employee_id)

            probability, flagged, factors, risk_level = _run_prediction(record)

            prediction_id = None
            if record.employee_id is not None:
                prediction_id = _persist(db, record.employee_id, probability, risk_level, factors)

            response = _to_response(
                employee_id=record.employee_id,
                probability=probability,
                flagged=flagged,
                factors=factors,
                risk_level=risk_level,
                prediction_id=prediction_id,
            )
            results.append(
                AttritionBatchResultItem(
                    index=index, employee_id=record.employee_id, status="predicted", prediction=response
                )
            )
            succeeded += 1
        except AppError as exc:
            db.rollback()
            results.append(
                AttritionBatchResultItem(
                    index=index,
                    employee_id=record.employee_id,
                    status="failed",
                    code=exc.code,
                    reason=exc.message,
                )
            )

    return AttritionBatchPredictResponse(
        total=len(payload.records),
        succeeded=succeeded,
        failed=len(payload.records) - succeeded,
        results=results,
    )


def _employee_to_out(employee: Employee, latest: AttritionPrediction | None) -> EmployeeOut:
    return EmployeeOut(
        id=employee.id,
        age=employee.age,
        department=employee.department,
        job_level=employee.job_level,
        monthly_income=employee.monthly_income,
        years_at_company=employee.years_at_company,
        years_since_last_promotion=employee.years_since_last_promotion,
        years_with_curr_manager=employee.years_with_curr_manager,
        total_working_years=employee.total_working_years,
        job_satisfaction=employee.job_satisfaction,
        environment_satisfaction=employee.environment_satisfaction,
        relationship_satisfaction=employee.relationship_satisfaction,
        performance_rating=employee.performance_rating,
        overtime=employee.overtime,
        business_travel=employee.business_travel,
        distance_from_home=employee.distance_from_home,
        percent_salary_hike=employee.percent_salary_hike,
        stock_option_level=employee.stock_option_level,
        latest_prediction=(
            LatestPredictionOut.model_validate(latest, from_attributes=True) if latest is not None else None
        ),
    )


def list_employees(db: Session, *, page: int, page_size: int) -> Page[EmployeeOut]:
    # This route doesn't itself need the model - it's a plain DB query. But
    # Phases.md Phase 11 is explicit that ALL FOUR attrition routes 503
    # ATTRITION_MODEL_MISSING when the artifact set is missing, not only the
    # prediction ones (F9.6: "attrition serving" is one coherent capability,
    # not four independent ones) - checked here purely as a gate, result
    # otherwise unused.
    predictor.get_artifacts()

    query = db.query(Employee).order_by(Employee.id.asc())
    total = query.count()
    employees = query.offset((page - 1) * page_size).limit(page_size).all()

    employee_ids = [e.id for e in employees]
    latest_by_employee: dict[int, AttritionPrediction] = {}
    if employee_ids:
        # One extra query for the whole page's latest predictions - no
        # per-employee loop query (Rules.md 4.5: no lazy-loading in a loop).
        latest_dates_subq = (
            db.query(
                AttritionPrediction.employee_id.label("employee_id"),
                func.max(AttritionPrediction.prediction_date).label("latest_date"),
            )
            .filter(AttritionPrediction.employee_id.in_(employee_ids))
            .group_by(AttritionPrediction.employee_id)
            .subquery()
        )
        latest_rows = (
            db.query(AttritionPrediction)
            .join(
                latest_dates_subq,
                (AttritionPrediction.employee_id == latest_dates_subq.c.employee_id)
                & (AttritionPrediction.prediction_date == latest_dates_subq.c.latest_date),
            )
            .all()
        )
        latest_by_employee = {row.employee_id: row for row in latest_rows}

    items = [_employee_to_out(employee, latest_by_employee.get(employee.id)) for employee in employees]
    return Page.create(items=items, total=total, page=page, page_size=page_size)


def get_model_info() -> ModelInfoResponse:
    artifacts = predictor.get_artifacts()
    return ModelInfoResponse(
        model_family=predictor.MODEL_FAMILY,
        imbalance_strategy=predictor.IMBALANCE_STRATEGY,
        calibration_method=artifacts.calibration_method,
        calibrated_decision_threshold=artifacts.calibrated_threshold,
        model_version=artifacts.model_version,
        feature_names=artifacts.feature_names,
        raw_evaluation_threshold=artifacts.raw_threshold,
        raw_evaluation_metrics=artifacts.raw_test_metrics,
        calibrated_evaluation_metrics=artifacts.calibrated_test_metrics,
        calibration_brier_improvement_mean=artifacts.calibration_brier_improvement_mean,
        calibration_brier_improvement_std=artifacts.calibration_brier_improvement_std,
        calibration_known_limitation=artifacts.calibration_known_limitation,
    )
