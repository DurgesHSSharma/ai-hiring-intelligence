"""Phase 10 completion, required before Phase 11 (attrition serving) can
load anything real: persists the calibrated model decision 70 already
validated. 06/07/08_calibration_*.py analysed sigmoid calibration across 4
seeds and printed a final sealed-test confirmation to the console, but never
joblib.dump()'d the fitted CalibratedClassifierCV and never updated
decision_threshold.json - by design, since all three were explicitly
"ANALYSIS ONLY, not production" (see each file's own docstring) and Phase 11
did not exist yet. Phase 11 needs an actual artifact to load, not console
output from a prior session. This script re-runs 07_calibration_
multiseed.py's exact, already-validated functions (imported, not
duplicated) end to end and adds only the persistence step - it makes no new
model/method/threshold decision.

Reuses (via importlib, same convention 05/06/07/08 already use for their own
digit-prefixed-filename imports):
  - 07_calibration_multiseed.py's run_one_seed() and recommend_threshold(),
    to reproduce the exact per-seed calibrated thresholds (42/43/44/45:
    0.1971/0.1935/0.2002/0.2112) and the exact cross-seed recommendation
    (mean, 0.2005) already recorded in Memory.md decision 70. Asserts the
    recomputed threshold matches that recorded value before writing
    anything - if it doesn't, something has silently drifted (a data file,
    a dependency version) and this script stops rather than shipping a
    different number under the same "0.2005" label.
  - 07_calibration_multiseed.py's build_smote_pipeline() (in turn from
    05_threshold_sweep.py), to fit the ONE shipped calibrated candidate:
    CalibratedClassifierCV(estimator=build_smote_pipeline("logreg", plain),
    method="sigmoid", cv=StratifiedKFold(5, shuffle=True, random_state=42)),
    fit on X_tr (raw, all 17 business columns, unencoded) at random_state=42
    throughout - the identical construction 07's own
    final_sealed_test_evaluation() already used to produce the sealed-test
    numbers decision 70 records (recall 0.660, 31/47; f1 0.477).

Writes two artifacts:
  1. calibrated_model.joblib - the fitted CalibratedClassifierCV. Because
     build_smote_pipeline()'s "preprocess" step lives INSIDE the estimator
     CalibratedClassifierCV wraps (05_threshold_sweep.py's leakage fix,
     decision 68), this object's own internal cv-fold estimators each carry
     their own fitted preprocessing - it takes the same raw, unencoded
     17-column input shape as feature_names.json / FEATURE_COLUMNS
     directly. It does NOT take preprocessor.joblib-transformed input, and
     must never be composed with a separate preprocessor.transform() call -
     doing so would encode the input twice. This is a structurally
     different serving contract from model.joblib (which DOES require
     preprocessor.joblib's transform() first, unchanged) - predictor.py
     must not confuse the two.
  2. decision_threshold.json gains a new "calibrated" section (threshold,
     calibration_method, model, strategy, artifact, a note distinguishing
     it from the existing top-level "threshold" field). The existing
     top-level threshold=0.550 field is left exactly as it was -
     decision 67 already establishes that number as a materially different,
     still-live thing (04_evaluate.py's own evaluation-script cutoff
     against the raw, uncalibrated model.joblib), not superseded by this.

Does NOT change SELECTED_MODEL/SELECTED_STRATEGY/DECISION_THRESHOLD in
03_train.py, does not retrain or compare models, does not change the
calibration method, does not choose a new threshold (asserts the recomputed
one matches what was already chosen), does not touch model.joblib /
preprocessor.joblib / metrics.json, and opens the sealed test set only for
one confirmatory read (never for tuning) - same discipline every prior
Phase 10 script in this directory already follows.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import brier_score_loss, confusion_matrix, log_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold, train_test_split

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"

# Decision 70's recorded recommendation - asserted against, not assumed.
_EXPECTED_RECOMMENDED_NAME = "mean"
_EXPECTED_THRESHOLD = 0.2005
_THRESHOLD_TOLERANCE = 0.0005

_MULTISEED_PATH = Path(__file__).resolve().parent / "07_calibration_multiseed.py"
_spec = importlib.util.spec_from_file_location("attrition_calibration_multiseed", _MULTISEED_PATH)
_multiseed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_multiseed)

_train = _multiseed._train
RANDOM_STATE = _multiseed.RANDOM_STATE
TEST_SIZE = _multiseed.TEST_SIZE
N_SPLITS = _multiseed.N_SPLITS
CALIBRATION_METHOD = _multiseed.CALIBRATION_METHOD
CALIBRATION_SEEDS = _multiseed.CALIBRATION_SEEDS
build_smote_pipeline = _multiseed.build_smote_pipeline
run_one_seed = _multiseed.run_one_seed
recommend_threshold = _multiseed.recommend_threshold
classification_metrics = _multiseed.classification_metrics


def main() -> None:
    print("=" * 78)
    print("Phase 10 completion: persisting the calibrated model decision 70 already validated.")
    print("=" * 78)

    X, y = _train.load_and_clean(_train.DATA_PATH)
    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=TEST_SIZE, stratify=y, random_state=RANDOM_STATE
    )
    y_tr_arr = np.asarray(y_tr)
    y_te_arr = np.asarray(y_te)
    prevalence = float(y_tr_arr.mean())
    print(f"train/OOF pool: {len(X_tr)} rows, {int(y_tr_arr.sum())} positive")
    print(f"sealed test set: {len(X_te)} rows, {int(y_te_arr.sum())} positive (one confirmatory read below)")

    plain = _train.build_plain_estimators()

    print(f"\nreproducing decision 70's 4-seed recommendation ({CALIBRATION_SEEDS})...")
    results = [run_one_seed(seed, X_tr, y_tr, y_tr_arr, plain, prevalence) for seed in CALIBRATION_SEEDS]
    rec = recommend_threshold(results, y_tr_arr)
    threshold = rec["recommended_threshold"]
    print(f"per-seed calibrated thresholds: {rec['thresholds_by_seed']}")
    print(f"recommended: {rec['recommended_name']} = {threshold:.4f}")

    if rec["recommended_name"] != _EXPECTED_RECOMMENDED_NAME or abs(threshold - _EXPECTED_THRESHOLD) > _THRESHOLD_TOLERANCE:
        raise RuntimeError(
            "Recomputed recommendation does not match Memory.md decision 70's recorded "
            f"result (expected {_EXPECTED_RECOMMENDED_NAME!r} ~= {_EXPECTED_THRESHOLD}, got "
            f"{rec['recommended_name']!r} = {threshold:.4f}). Stopping rather than silently "
            "persisting a different threshold under the 0.2005 label - re-verify against "
            "Memory.md and the underlying data/dependencies before proceeding."
        )
    print("matches Memory.md decision 70's recorded recommendation - proceeding.")

    # The one shipped calibrated model: identical construction to 07's own
    # final_sealed_test_evaluation(), fit here directly (rather than calling
    # that function, which returns metrics only) so this script owns the
    # actual fitted object to persist.
    inner_cv = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)
    calibrated_model = CalibratedClassifierCV(
        estimator=build_smote_pipeline("logreg", plain), method=CALIBRATION_METHOD, cv=inner_cv
    )
    calibrated_model.fit(X_tr, y_tr)

    print("\nconfirmatory sealed-test read (one time, this candidate only):")
    test_proba = calibrated_model.predict_proba(X_te)[:, 1]
    metrics = classification_metrics(y_te_arr, test_proba, threshold)
    pred = (test_proba >= threshold).astype(int)
    cm = confusion_matrix(y_te_arr, pred).tolist()
    sealed_test_brier = float(brier_score_loss(y_te_arr, test_proba))
    sealed_test_log_loss = float(log_loss(y_te_arr, test_proba))
    sealed_test_roc_auc = float(roc_auc_score(y_te_arr, test_proba))
    sealed_test_mean_predicted = float(test_proba.mean())
    print(
        f"  brier={sealed_test_brier:.4f} log_loss={sealed_test_log_loss:.4f} "
        f"roc_auc={sealed_test_roc_auc:.4f} mean_predicted={sealed_test_mean_predicted:.4f}"
    )
    print(
        f"  threshold={threshold:.4f}  precision={metrics['precision']:.3f} "
        f"recall={metrics['recall']:.3f} f1={metrics['f1']:.3f}  confusion_matrix={cm}"
    )

    # Cross-seed Brier improvement (calibrated vs. uncalibrated), computed
    # here from the same 4-seed `results` already produced above - not a new
    # experiment, just carried into the persisted record instead of only
    # ever having lived in a prior session's console output (Memory.md
    # decision 70 quotes it as prose: "0.0629 +/- 0.0015").
    brier_improvements = [r["brier_improvement"] for r in results]
    brier_improvement_mean = float(np.mean(brier_improvements))
    brier_improvement_std = float(np.std(brier_improvements))

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(calibrated_model, ARTIFACT_DIR / "calibrated_model.joblib")

    threshold_path = ARTIFACT_DIR / "decision_threshold.json"
    with open(threshold_path, encoding="utf-8") as f:
        threshold_doc = json.load(f)
    threshold_doc["calibrated"] = {
        "threshold": round(threshold, 4),
        "calibration_method": CALIBRATION_METHOD,
        "model": "logreg",
        "strategy": "smote",
        "artifact": "calibrated_model.joblib",
        "chosen_from": "07_calibration_multiseed.py recommend_threshold() (mean across seeds 42/43/44/45)",
        "note": (
            "Serving-time binary threshold for calibrated_model.joblib's output only. "
            "Distinct from the top-level 'threshold' field above (0.550), which remains "
            "04_evaluate.py's own evaluation-script cutoff against the raw, uncalibrated "
            "model.joblib and is unchanged by this file - see Memory.md decision 67."
        ),
        "brier_improvement_vs_uncalibrated_mean": round(brier_improvement_mean, 4),
        "brier_improvement_vs_uncalibrated_std": round(brier_improvement_std, 4),
        "sealed_test_metrics": {
            "brier_score": round(sealed_test_brier, 4),
            "log_loss": round(sealed_test_log_loss, 4),
            "roc_auc": round(sealed_test_roc_auc, 4),
            "mean_predicted_probability": round(sealed_test_mean_predicted, 4),
            "precision": round(metrics["precision"], 4),
            "recall": round(metrics["recall"], 4),
            "f1": round(metrics["f1"], 4),
            "confusion_matrix": cm,
            "n_test": int(len(y_te_arr)),
            "n_test_positive": int(y_te_arr.sum()),
        },
        "known_limitation": (
            "The highest calibration bin under-predicts actual risk by roughly 12-15 "
            "percentage points (multi-seed confirmed, Memory.md decision 70) - the "
            "calibrated probability for the highest-risk employees is a conservative "
            "floor, not an exact figure."
        ),
    }
    with open(threshold_path, "w", encoding="utf-8") as f:
        json.dump(threshold_doc, f, indent=2)

    print(f"\nsaved calibrated_model.joblib and updated decision_threshold.json in {ARTIFACT_DIR}")


if __name__ == "__main__":
    main()
