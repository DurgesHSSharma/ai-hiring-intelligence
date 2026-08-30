"""Phase 10: compare Logistic Regression, Random Forest, and XGBoost for
attrition prediction under two imbalance-handling strategies, then serialise
a hardcoded final choice (see SELECTED_MODEL/SELECTED_STRATEGY/
DECISION_THRESHOLD below) rather than an automatic CV-F1 argmax.

The test split created here is never scored. 04_evaluate.py owns the one
sealed evaluation run against it (Phases.md Phase 10 acceptance).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from imblearn.over_sampling import SMOTE
from imblearn.pipeline import Pipeline as ImbPipeline
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_validate, train_test_split
from xgboost import XGBClassifier

RANDOM_STATE = 42
TEST_SIZE = 0.2
N_SPLITS = 5
SCORING = ["accuracy", "precision", "recall", "f1", "roc_auc"]

# Logistic Regression + SMOTE, not an automatic CV-F1 argmax. The argmax
# this file used to compute picked this same config by F1=0.479+/-0.033 vs.
# XGBoost+SMOTE's 0.476+/-0.074 - a 0.003 gap smaller than either config's
# own noise, i.e. not a real result; a different random_state could flip
# it. 05_threshold_sweep.py settled it on real evidence instead, in two
# rounds: round 1 (single seed 42) found the two SMOTE configs' precision-
# recall curves cross near recall~0.38, with Logistic Regression ahead at
# recall 0.40-0.90. Round 2 fixed a real preprocessing-leakage gap found in
# round 1 (the preprocessor was fit once on the whole training fold before
# CV, not inside each fold) and re-ran the comparison across 4 independent
# StratifiedKFold seeds (42/43/44/45). Logistic Regression + SMOTE won
# every one of the 4 seeds x 3 recall targets (>=0.60/0.70/0.80) = 12
# recall-matched comparisons - 12/12, zero ties, zero XGBoost wins. This is
# NOT a whole-curve dominance claim - only the tested recall range
# (0.60-0.80) was checked across all 4 seeds. DECISION_THRESHOLD=0.550
# targets recall~0.70: confirmed by the fold-safe sweep at seed 42
# (precision=0.389 at exactly threshold=0.550, matching round 1's number
# almost exactly), and it sits inside the narrow [0.538, 0.550] range every
# one of the 4 tested seeds independently produced for the same recall~0.70
# target - not an artifact of one particular fold assignment or of the
# leakage since fixed. See docs/EVALUATION.md's Phase 10 section and
# decisions 66/68. Separately: neither this model's nor a class_weight=
# "balanced" LogReg's raw predict_proba is a calibrated real-world
# probability (mean predicted ~0.37 vs. true prevalence ~0.16; a raw 0.60
# corresponds to an actual ~21% observed rate, not 60%) - decision 69. This
# threshold is a decision cutoff for evaluation, not a claim about the
# probability's real-world meaning.
SELECTED_MODEL = "logreg"
SELECTED_STRATEGY = "smote"
DECISION_THRESHOLD = 0.550

ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = ROOT / "data" / "raw" / "WA_Fn-UseC_-HR-Employee-Attrition.csv"
ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"

# 02_preprocessing.py's filename starts with a digit and can't be `import`ed
# normally (see its own docstring) — loaded the same way it documents.
_PREPROCESSING_PATH = Path(__file__).resolve().parent / "02_preprocessing.py"
_spec = importlib.util.spec_from_file_location("attrition_preprocessing", _PREPROCESSING_PATH)
_preprocessing = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_preprocessing)
load_and_clean = _preprocessing.load_and_clean
build_pipeline = _preprocessing.build_pipeline
FEATURE_COLUMNS = _preprocessing.FEATURE_COLUMNS


def build_balanced_estimators(scale_pos_weight: float) -> dict[str, object]:
    """One class-weighted estimator per model family; no resampling."""
    return {
        "logreg": LogisticRegression(
            class_weight="balanced", max_iter=1000, random_state=RANDOM_STATE
        ),
        "random_forest": RandomForestClassifier(
            class_weight="balanced", random_state=RANDOM_STATE
        ),
        "xgboost": XGBClassifier(
            scale_pos_weight=scale_pos_weight, random_state=RANDOM_STATE, eval_metric="logloss"
        ),
    }


def build_plain_estimators() -> dict[str, object]:
    """Unweighted estimators, paired with SMOTE instead of class weighting."""
    return {
        "logreg": LogisticRegression(max_iter=1000, random_state=RANDOM_STATE),
        "random_forest": RandomForestClassifier(random_state=RANDOM_STATE),
        "xgboost": XGBClassifier(random_state=RANDOM_STATE, eval_metric="logloss"),
    }


def run_cv(estimator: object, X: np.ndarray, y: pd.Series, cv: StratifiedKFold) -> dict[str, float]:
    """Cross-validate one estimator/pipeline. Returns {metric}_mean/{metric}_std for SCORING."""
    results = cross_validate(estimator, X, y, cv=cv, scoring=SCORING, error_score="raise")
    out: dict[str, float] = {}
    for metric in SCORING:
        scores = results[f"test_{metric}"]
        out[f"{metric}_mean"] = float(np.mean(scores))
        out[f"{metric}_std"] = float(np.std(scores))
    return out


def format_row(row: dict) -> str:
    parts = [f"{row['model']:<13} {row['strategy']:<22}"]
    for metric in SCORING:
        parts.append(f"{metric}={row[f'{metric}_mean']:.3f}+/-{row[f'{metric}_std']:.3f}")
    return "  ".join(parts)


def main() -> None:
    X, y = load_and_clean(DATA_PATH)
    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=TEST_SIZE, stratify=y, random_state=RANDOM_STATE
    )
    print(f"train: {len(X_tr)} rows, {int(y_tr.sum())} positive")
    print(f"test (sealed until 04_evaluate.py): {len(X_te)} rows, {int(y_te.sum())} positive")

    preprocessor = build_pipeline()
    X_tr_enc = preprocessor.fit_transform(X_tr)
    # Transformed here only to prove the fitted preprocessor also handles the
    # held-out split's shape/categories cleanly. y_te is never touched and no
    # model sees this array until 04_evaluate.py's own single evaluation run.
    X_te_enc = preprocessor.transform(X_te)
    print(f"preprocessor: {X_tr_enc.shape[1]} encoded columns; test split transforms cleanly {X_te_enc.shape}")

    scale_pos_weight = float((y_tr == 0).sum() / (y_tr == 1).sum())
    balanced = build_balanced_estimators(scale_pos_weight)
    plain = build_plain_estimators()
    cv = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)

    rows = []
    for name in balanced:
        metrics = run_cv(balanced[name], X_tr_enc, y_tr, cv)
        rows.append({"model": name, "strategy": "class_weight_balanced", **metrics})

        # SMOTE lives inside this pipeline, never applied to X_tr_enc up
        # front: cross_validate clones the pipeline per fold and calls
        # fit_resample() only on that fold's training rows, so a synthetic
        # neighbour of a validation-fold point can never leak into training.
        smote_pipeline = ImbPipeline(
            [("smote", SMOTE(random_state=RANDOM_STATE)), ("clf", plain[name])]
        )
        metrics = run_cv(smote_pipeline, X_tr_enc, y_tr, cv)
        rows.append({"model": name, "strategy": "smote", **metrics})

    print("\n5-fold CV on the training split only (test set untouched):")
    for row in rows:
        print(format_row(row))

    results_df = pd.DataFrame(rows)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    results_df.to_csv(ARTIFACT_DIR / "cv_results.csv", index=False)

    best = results_df[
        (results_df["model"] == SELECTED_MODEL) & (results_df["strategy"] == SELECTED_STRATEGY)
    ].iloc[0]
    print(
        f"\nSelected (hardcoded, not CV-F1 argmax - see module docstring): "
        f"{SELECTED_MODEL} / {SELECTED_STRATEGY}, decision_threshold={DECISION_THRESHOLD} "
        f"(from 05_threshold_sweep.py). This config's own CV numbers: "
        f"f1={best['f1_mean']:.3f}+/-{best['f1_std']:.3f}, "
        f"recall={best['recall_mean']:.3f}+/-{best['recall_std']:.3f}, "
        f"precision={best['precision_mean']:.3f}+/-{best['precision_std']:.3f}, "
        f"accuracy={best['accuracy_mean']:.3f}+/-{best['accuracy_std']:.3f} (reported, not decisive)"
    )

    if SELECTED_STRATEGY == "smote":
        final_model = ImbPipeline(
            [("smote", SMOTE(random_state=RANDOM_STATE)), ("clf", plain[SELECTED_MODEL])]
        )
    else:
        final_model = balanced[SELECTED_MODEL]
    final_model.fit(X_tr_enc, y_tr)

    joblib.dump(final_model, ARTIFACT_DIR / "model.joblib")
    joblib.dump(preprocessor, ARTIFACT_DIR / "preprocessor.joblib")
    with open(ARTIFACT_DIR / "feature_names.json", "w", encoding="utf-8") as f:
        json.dump(FEATURE_COLUMNS, f, indent=2)
    with open(ARTIFACT_DIR / "decision_threshold.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "threshold": DECISION_THRESHOLD,
                "model": SELECTED_MODEL,
                "strategy": SELECTED_STRATEGY,
                "target_recall": 0.70,
                "chosen_from": "05_threshold_sweep.py out-of-fold precision-recall curve",
            },
            f,
            indent=2,
        )

    print(
        f"\nsaved model.joblib ({SELECTED_MODEL}/{SELECTED_STRATEGY}), preprocessor.joblib, "
        f"feature_names.json, decision_threshold.json, cv_results.csv to {ARTIFACT_DIR}"
    )


if __name__ == "__main__":
    main()
