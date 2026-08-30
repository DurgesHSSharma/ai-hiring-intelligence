"""Phase 10: the one sealed evaluation of the chosen model against the held-out
test set. Reproduces 03_train.py's split deterministically (identical
random_state/test_size) rather than loading a persisted test set, then scores
the serialised model exactly once, at the decision threshold recorded in
artifacts/decision_threshold.json (05_threshold_sweep.py's finding) rather
than predict()'s implicit 0.5.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split

# Must match 03_train.py exactly for the reproduced split to be the same one
# that split's training fold was carved out of.
RANDOM_STATE = 42
TEST_SIZE = 0.2
MODEL_VERSION = "1"

ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = ROOT / "data" / "raw" / "WA_Fn-UseC_-HR-Employee-Attrition.csv"
ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"

_PREPROCESSING_PATH = Path(__file__).resolve().parent / "02_preprocessing.py"
_spec = importlib.util.spec_from_file_location("attrition_preprocessing", _PREPROCESSING_PATH)
_preprocessing = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_preprocessing)
load_and_clean = _preprocessing.load_and_clean

# performance_rating has only 2 distinct values in this dataset (decision 56);
# these three are confounded with tenure/career stage (D61, decision 61).
# Both must be called out wherever they surface in the ranking below, not
# read as independent causal drivers.
NEAR_CONSTANT_FEATURES = {"performance_rating"}
TENURE_CONFOUNDED_FEATURES = {
    "years_at_company",
    "years_since_last_promotion",
    "years_with_curr_manager",
}


def get_classifier(model: object) -> object:
    """Unwrap the fitted estimator from an imblearn SMOTE pipeline, if any."""
    if hasattr(model, "named_steps"):
        return model.named_steps["clf"]
    return model


def ranked_feature_importances(model: object, encoded_names: list[str]) -> list[tuple[str, float]]:
    """Global feature importances (tree gain or |coefficient|), descending."""
    clf = get_classifier(model)
    if hasattr(clf, "feature_importances_"):
        values = clf.feature_importances_
    elif hasattr(clf, "coef_"):
        values = np.abs(clf.coef_[0])
    else:
        return []
    ranked = sorted(zip(encoded_names, values), key=lambda pair: pair[1], reverse=True)
    return [(name, float(value)) for name, value in ranked]


def main() -> None:
    X, y = load_and_clean(DATA_PATH)
    _, X_te, _, y_te = train_test_split(
        X, y, test_size=TEST_SIZE, stratify=y, random_state=RANDOM_STATE
    )

    model = joblib.load(ARTIFACT_DIR / "model.joblib")
    preprocessor = joblib.load(ARTIFACT_DIR / "preprocessor.joblib")
    with open(ARTIFACT_DIR / "decision_threshold.json", encoding="utf-8") as f:
        threshold_config = json.load(f)
    threshold = threshold_config["threshold"]

    X_te_enc = preprocessor.transform(X_te)
    y_proba = model.predict_proba(X_te_enc)[:, 1]
    # The sweep-chosen threshold (05_threshold_sweep.py), not model.predict()'s
    # implicit 0.5 - see 03_train.py's DECISION_THRESHOLD and decision 66.
    y_pred = (y_proba >= threshold).astype(int)

    metrics = {
        "accuracy": float(accuracy_score(y_te, y_pred)),
        "precision": float(precision_score(y_te, y_pred)),
        "recall": float(recall_score(y_te, y_pred)),
        "f1": float(f1_score(y_te, y_pred)),
        "roc_auc": float(roc_auc_score(y_te, y_proba)),
    }
    cm = confusion_matrix(y_te, y_pred).tolist()

    print(
        "FINAL SEALED TEST-SET METRICS (opened once, this run) - not CV, not "
        "out-of-fold; distinct from every number in 03_train.py's cv_results.csv "
        "or 05_threshold_sweep.py's threshold_sweep.csv."
    )
    print(f"test set: {len(X_te)} rows, {int(y_te.sum())} positive")
    print(f"decision threshold: {threshold} (from {threshold_config['chosen_from']})")
    print("test metrics:")
    for name, value in metrics.items():
        print(f"  {name:<10} {value:.3f}")
    print(f"confusion matrix [[TN, FP], [FN, TP]]: {cm}")
    print(
        "accuracy is reported above for completeness only, not as the basis for model "
        f"choice: predicting 'No' for every row would score {(y_te == 0).mean():.3f} "
        "accuracy on this test set while catching zero actual leavers."
    )

    encoded_names = list(preprocessor.get_feature_names_out())
    ranked = ranked_feature_importances(model, encoded_names)
    print("\nfeature importances (top 10):")
    for name, value in ranked[:10]:
        base_name = name.split("__", 1)[-1]
        flags = []
        if base_name in NEAR_CONSTANT_FEATURES:
            flags.append("near-constant in this dataset (decision 56) - treat with caution")
        if base_name in TENURE_CONFOUNDED_FEATURES:
            flags.append("confounded with tenure/career stage (D61) - not an independent driver")
        suffix = f"  [{'; '.join(flags)}]" if flags else ""
        print(f"  {name:<35} {value:.4f}{suffix}")

    model_type = type(get_classifier(model)).__name__
    strategy = "smote" if hasattr(model, "named_steps") else "class_weight_balanced"
    metrics_payload = {
        "version": MODEL_VERSION,
        "model_type": model_type,
        "imbalance_strategy": strategy,
        "decision_threshold": threshold,
        "test_set_size": len(X_te),
        "test_set_positives": int(y_te.sum()),
        "test_metrics": metrics,
        "confusion_matrix": cm,
        "feature_importances": ranked,
    }
    with open(ARTIFACT_DIR / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics_payload, f, indent=2)
    print(f"\nsaved metrics.json to {ARTIFACT_DIR}")


if __name__ == "__main__":
    main()
