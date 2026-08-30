"""Attrition model predictor (PRD F9.5/F9.6/F11, Phases.md Phase 11). Loads
the finalized Phase 10 artifacts once and reuses them (Rules.md 4.6) - never
fit here, never reloaded per request. main.py's lifespan calls
load_artifacts()/set_artifacts() exactly once at startup.

Two distinct artifact pairs, two distinct jobs, deliberately not conflated
(Memory.md decision 70):
  - calibrated_model.joblib serves the probability actually returned to
    callers - a sigmoid-calibrated CalibratedClassifierCV
    (ml/attrition/09_finalize_calibrated_model.py). Its wrapped estimator
    already embeds preprocessing + SMOTE + the classifier as one pipeline,
    so it takes the raw, unencoded 17-column feature row directly - it must
    never be composed with a separate preprocessor.transform() call, and
    its output must never be confused with model.joblib's raw probability
    (decision 69: the raw SMOTE classifier overstates real attrition risk
    by roughly 2.3-2.4x).
  - model.joblib + preprocessor.joblib, the original Phase 10 artifacts,
    stay loaded for exactly one purpose: per-prediction top_factors, reusing
    the same coefficient-magnitude convention metrics.json's global
    feature_importances already established. Never used to compute the
    served probability.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from app.core.exceptions import ModelUnavailableError

logger = logging.getLogger(__name__)

MODEL_FAMILY = "Logistic Regression"
IMBALANCE_STRATEGY = "SMOTE"
TOP_FACTORS_COUNT = 5


@dataclass(frozen=True)
class AttritionArtifacts:
    """Everything predictor.py needs, loaded once and passed around as one
    immutable bundle rather than several loose module globals."""

    calibrated_model: object
    explain_model: object
    preprocessor: object
    feature_names: list[str]
    calibrated_threshold: float
    calibration_method: str
    raw_threshold: float
    model_version: str
    raw_test_metrics: dict
    calibrated_test_metrics: dict
    calibration_known_limitation: str
    calibration_brier_improvement_mean: float | None
    calibration_brier_improvement_std: float | None


_artifacts: AttritionArtifacts | None = None


def _require_file(path: Path) -> Path:
    if not path.is_file():
        raise ModelUnavailableError(
            f"Attrition model artifact not found: {path}. Run "
            "ml/attrition/03_train.py and "
            "ml/attrition/09_finalize_calibrated_model.py to produce it, or "
            "restore it to its usual location.",
            code="ATTRITION_MODEL_MISSING",
            details={"missing_path": str(path)},
        )
    return path


def load_artifacts(calibrated_model_path: str | Path) -> AttritionArtifacts:
    """Loads every artifact predictor.py needs from the directory containing
    calibrated_model_path (settings.ATTRITION_MODEL_PATH). Raises
    ModelUnavailableError(code=ATTRITION_MODEL_MISSING) naming the first
    missing file or artifact inconsistency found - never returns a
    partially-loaded or internally-inconsistent bundle.
    """
    calibrated_path = _require_file(Path(calibrated_model_path))
    artifact_dir = calibrated_path.parent

    model_path = _require_file(artifact_dir / "model.joblib")
    preprocessor_path = _require_file(artifact_dir / "preprocessor.joblib")
    feature_names_path = _require_file(artifact_dir / "feature_names.json")
    threshold_path = _require_file(artifact_dir / "decision_threshold.json")
    metrics_path = _require_file(artifact_dir / "metrics.json")

    try:
        calibrated_model = joblib.load(calibrated_path)
        explain_model = joblib.load(model_path)
        preprocessor = joblib.load(preprocessor_path)
        with open(feature_names_path, encoding="utf-8") as f:
            feature_names = list(json.load(f))
        with open(threshold_path, encoding="utf-8") as f:
            threshold_doc = json.load(f)
        with open(metrics_path, encoding="utf-8") as f:
            metrics_doc = json.load(f)
    except ModelUnavailableError:
        raise
    except Exception as exc:
        raise ModelUnavailableError(
            f"Attrition model artifacts exist but could not be loaded: {exc}",
            code="ATTRITION_MODEL_MISSING",
            details={"artifact_dir": str(artifact_dir)},
        ) from exc

    calibrated_section = threshold_doc.get("calibrated")
    if not calibrated_section:
        raise ModelUnavailableError(
            "decision_threshold.json has no 'calibrated' section - run "
            "ml/attrition/09_finalize_calibrated_model.py to produce it.",
            code="ATTRITION_MODEL_MISSING",
            details={"artifact_dir": str(artifact_dir)},
        )

    # Train-serve skew guard, checked once here rather than per request
    # (Phases.md Phase 11): preprocessor.joblib must have been fit on
    # exactly the raw columns feature_names.json records, and
    # model.joblib's classifier must expect exactly as many encoded columns
    # as preprocessor.joblib actually produces. Either mismatch means the
    # artifact set itself is inconsistent (e.g. mixed from two different
    # training runs), not something a caller's request could ever trigger.
    preprocess_step = preprocessor.named_steps["preprocess"]
    fitted_raw_columns = set(getattr(preprocess_step, "feature_names_in_", []))
    if fitted_raw_columns and fitted_raw_columns != set(feature_names):
        raise ModelUnavailableError(
            "preprocessor.joblib was fit on a different raw feature set than "
            "feature_names.json records - the artifact set is inconsistent.",
            code="ATTRITION_MODEL_MISSING",
            details={
                "preprocessor_columns": sorted(fitted_raw_columns),
                "feature_names_json": sorted(feature_names),
            },
        )
    encoded_width = len(preprocess_step.get_feature_names_out())
    clf_width = explain_model.named_steps["clf"].coef_.shape[1]
    if encoded_width != clf_width:
        raise ModelUnavailableError(
            "preprocessor.joblib's encoded output width does not match "
            "model.joblib's expected input width - the artifact set is "
            "inconsistent.",
            code="ATTRITION_MODEL_MISSING",
            details={"encoded_width": encoded_width, "model_expected_width": clf_width},
        )

    return AttritionArtifacts(
        calibrated_model=calibrated_model,
        explain_model=explain_model,
        preprocessor=preprocessor,
        feature_names=feature_names,
        calibrated_threshold=float(calibrated_section["threshold"]),
        calibration_method=str(calibrated_section["calibration_method"]),
        raw_threshold=float(threshold_doc["threshold"]),
        model_version=str(metrics_doc.get("version", "unknown")),
        raw_test_metrics=dict(metrics_doc.get("test_metrics", {})),
        calibrated_test_metrics=dict(calibrated_section.get("sealed_test_metrics", {})),
        calibration_known_limitation=str(calibrated_section.get("known_limitation", "")),
        calibration_brier_improvement_mean=calibrated_section.get("brier_improvement_vs_uncalibrated_mean"),
        calibration_brier_improvement_std=calibrated_section.get("brier_improvement_vs_uncalibrated_std"),
    )


def set_artifacts(artifacts: AttritionArtifacts | None) -> None:
    """Sets (or clears, with None) the process-wide loaded artifacts.
    Called exactly once from main.py's lifespan (Rules.md 4.6 - never per
    request). Tests also use this directly to simulate
    ATTRITION_MODEL_MISSING without touching real files on disk.
    """
    global _artifacts
    _artifacts = artifacts


def is_loaded() -> bool:
    return _artifacts is not None


def get_artifacts() -> AttritionArtifacts:
    """Raises ModelUnavailableError(code=ATTRITION_MODEL_MISSING) if the
    model was never loaded (missing artifact at startup). The one place
    every attrition route/service function goes through, so a missing
    model degrades only the attrition routes (Phases.md Phase 11
    acceptance), never the rest of the app.
    """
    if _artifacts is None:
        raise ModelUnavailableError(
            "The attrition model is not loaded. Run ml/attrition/03_train.py "
            "and ml/attrition/09_finalize_calibrated_model.py, then restart "
            "the application.",
            code="ATTRITION_MODEL_MISSING",
        )
    return _artifacts


def predict_proba(feature_row: pd.DataFrame) -> float:
    """The one and only place the served probability is computed - always
    calibrated_model.predict_proba, never explain_model's raw output
    (decision 69). Clamped to [0, 1] per Rules.md 5.4, though
    CalibratedClassifierCV's output is already a valid probability by
    construction.
    """
    artifacts = get_artifacts()
    proba = float(artifacts.calibrated_model.predict_proba(feature_row)[0, 1])
    return min(1.0, max(0.0, proba))


def top_factors(feature_row: pd.DataFrame, top_n: int = TOP_FACTORS_COUNT) -> list[dict]:
    """Per-prediction signed contributions: coefficient x this employee's
    own encoded feature value, from the uncalibrated model.joblib +
    preprocessor.joblib pair - the same coefficient-magnitude convention
    metrics.json's global feature_importances already uses (Phase 10),
    evaluated per-row instead of globally. Deliberately not computed from
    calibrated_model.joblib: CalibratedClassifierCV wraps several
    independently fold-fitted pipelines with no single coefficient vector
    to read, whereas model.joblib is the one, already-validated, single
    fitted classifier this project's existing explainability convention was
    built around (Memory.md decision 63 - SHAP was deferred, not built, for
    exactly this scope).
    """
    artifacts = get_artifacts()
    encoded = np.asarray(artifacts.preprocessor.transform(feature_row))[0]
    clf = artifacts.explain_model.named_steps["clf"]
    names = artifacts.preprocessor.named_steps["preprocess"].get_feature_names_out()
    contributions = clf.coef_[0] * encoded

    ranked = sorted(zip(names, contributions), key=lambda pair: abs(pair[1]), reverse=True)
    return [
        {
            "feature": name.split("__", 1)[1] if "__" in name else name,
            "contribution": float(value),
        }
        for name, value in ranked[:top_n]
    ]
