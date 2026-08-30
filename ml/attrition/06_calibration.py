"""Phase 10 calibration validation - ANALYSIS ONLY, not production.

Decision 69 found Logistic Regression + SMOTE's raw predict_proba overstates
real attrition risk by ~2.3-2.4x (mean predicted ~0.37 vs. true prevalence
~0.16) and is not a calibrated real-world probability. This script tests
whether sigmoid (Platt) calibration fixes that, at what cost to ranking
quality (ROC-AUC) and to the recall/precision operating point Phase 10
already chose, and whether PRD F9.7's fixed Low/Medium/High bands
(<30%/30-60%/>60%) are actually usable once probabilities are calibrated.

Does NOT change SELECTED_MODEL, SELECTED_STRATEGY, or DECISION_THRESHOLD in
03_train.py, and does not touch Phase 11 (which does not exist yet). No new
production artifact is saved - the calibrated pipeline built here is fit and
scored in-memory only, for this analysis.

Calibration method: CalibratedClassifierCV(method="sigmoid"). Isotonic was
not used - the training fold has only ~190 positive cases, and isotonic
regression's much larger effective parameter count overfits readily at that
scale; sigmoid's two-parameter logistic mapping is the conservative choice
here, per explicit instruction.

Leakage discipline, identical to 05_threshold_sweep.py's fold-safe pipeline:
preprocessing, SMOTE, and the classifier are one imblearn.pipeline.Pipeline,
reused via build_smote_pipeline(). CalibratedClassifierCV wraps that whole
pipeline as its `estimator`, so its own internal cv split refits
preprocessing + SMOTE + the classifier on the sub-training portion of each
internal fold and fits the sigmoid mapping only on that fold's held-out
calibration portion - imblearn's Pipeline.predict_proba() skips the SMOTE
step entirely at prediction/calibration time, so the calibration portion is
never resampled. cross_val_predict then wraps THAT whole
CalibratedClassifierCV as its own estimator for an outer StratifiedKFold, so
out-of-fold probabilities come from a genuinely nested CV: no row's own fold
ever contributes to fitting preprocessing, SMOTE, the classifier, or the
calibration mapping used to score it.

The sealed test set is touched exactly once, at the very end, for the final
calibrated candidate only - never for the uncalibrated model (already
reported in 04_evaluate.py), never for tuning anything here.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import (
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_predict, train_test_split

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
CALIBRATION_METHOD = "sigmoid"
RAW_THRESHOLD = 0.550
N_BINS = 10
F9_7_BANDS = [("low_lt_30", 0.0, 0.30), ("medium_30_60", 0.30, 0.60), ("high_gt_60", 0.60, 1.0)]

# 05_threshold_sweep.py's filename starts with a digit and can't be
# `import`ed normally (same constraint 02_preprocessing.py documents).
# Loading it reuses its exact fold-safe pipeline builder and split
# constants, transitively also reusing 03_train.py's estimator
# definitions - this script introduces no new pipeline construction of
# its own beyond adding CalibratedClassifierCV around the existing one.
_SWEEP_PATH = Path(__file__).resolve().parent / "05_threshold_sweep.py"
_spec = importlib.util.spec_from_file_location("attrition_sweep", _SWEEP_PATH)
_sweep = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sweep)

_train = _sweep._train
RANDOM_STATE = _sweep.RANDOM_STATE
TEST_SIZE = _sweep.TEST_SIZE
N_SPLITS = _sweep.N_SPLITS
build_smote_pipeline = _sweep.build_smote_pipeline


def reliability_bins(name: str, proba: np.ndarray, y: np.ndarray, n_bins: int = N_BINS) -> pd.DataFrame:
    """Quantile reliability bins with real per-bin counts (decision 69's fix, reused)."""
    bin_labels = pd.qcut(proba, q=n_bins, duplicates="drop")
    grouped = (
        pd.DataFrame({"proba": proba, "y": y, "bin": bin_labels})
        .groupby("bin", observed=True)
        .agg(
            n=("y", "size"),
            n_positive=("y", "sum"),
            mean_predicted=("proba", "mean"),
            fraction_positive=("y", "mean"),
        )
        .reset_index(drop=True)
    )
    grouped.insert(0, "model", name)
    grouped.insert(1, "bin", range(len(grouped)))
    return grouped


def classification_metrics(y: np.ndarray, proba: np.ndarray, threshold: float) -> dict:
    y_pred = (proba >= threshold).astype(int)
    return {
        "precision": float(precision_score(y, y_pred, zero_division=0)),
        "recall": float(recall_score(y, y_pred, zero_division=0)),
        "f1": float(f1_score(y, y_pred, zero_division=0)),
    }


def best_f1_threshold(proba: np.ndarray, y: np.ndarray) -> float:
    precision, recall, thresholds = precision_recall_curve(y, proba)
    precision, recall = precision[:-1], recall[:-1]
    denom = precision + recall
    f1 = np.where(denom > 0, 2 * precision * recall / np.where(denom > 0, denom, 1), 0.0)
    return float(thresholds[int(np.argmax(f1))])


def find_matched_recall_threshold(proba: np.ndarray, y: np.ndarray, target_recall: float) -> tuple[float, float, float]:
    """Threshold on `proba` whose recall is closest to target_recall. Returns (threshold, precision, recall)."""
    precision, recall, thresholds = precision_recall_curve(y, proba)
    precision, recall = precision[:-1], recall[:-1]
    idx = int(np.argmin(np.abs(recall - target_recall)))
    return float(thresholds[idx]), float(precision[idx]), float(recall[idx])


def score_distribution(proba: np.ndarray) -> dict:
    return {
        "min": float(proba.min()),
        "max": float(proba.max()),
        "mean": float(proba.mean()),
        "median": float(np.median(proba)),
        "p95": float(np.percentile(proba, 95)),
        "p99": float(np.percentile(proba, 99)),
    }


def f9_7_band_counts(proba: np.ndarray) -> dict:
    n = len(proba)
    out = {}
    for name, lo, hi in F9_7_BANDS:
        if hi >= 1.0:
            count = int(np.sum(proba > lo))
        else:
            count = int(np.sum((proba >= lo) & (proba <= hi))) if lo > 0 else int(np.sum(proba < hi))
        out[name] = {"count": count, "pct": round(100 * count / n, 2)}
    return out


def plot_calibration_curve(bins_uncal: pd.DataFrame, bins_cal: pd.DataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot([0, 1], [0, 1], linestyle="--", color="gray", label="perfect calibration")
    ax.plot(bins_uncal["mean_predicted"], bins_uncal["fraction_positive"], marker="o", label="uncalibrated")
    ax.plot(bins_cal["mean_predicted"], bins_cal["fraction_positive"], marker="s", label="calibrated (sigmoid)")
    ax.set_xlabel("mean predicted probability (bin)")
    ax.set_ylabel("actual fraction positive (bin)")
    ax.set_title("Reliability curve: Logistic Regression + SMOTE, training-fold OOF")
    ax.legend()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def main() -> None:
    print("=" * 78)
    print("Phase 10 calibration validation - ANALYSIS ONLY, not production.")
    print(f"Calibration method: CalibratedClassifierCV(method='{CALIBRATION_METHOD}')")
    print("All numbers below except the final section come from training-fold")
    print("out-of-fold predictions - the sealed test set is opened exactly once,")
    print("at the very end, for the final calibrated candidate only.")
    print("=" * 78)

    X, y = _train.load_and_clean(_train.DATA_PATH)
    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=TEST_SIZE, stratify=y, random_state=RANDOM_STATE
    )
    y_tr_arr = np.asarray(y_tr)
    y_te_arr = np.asarray(y_te)
    prevalence = float(y_tr_arr.mean())

    plain = _train.build_plain_estimators()
    outer_cv = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)
    inner_cv = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)

    # --- 1 & 3: uncalibrated OOF (single-level CV, fold-safe throughout) ---
    uncalibrated_pipeline = build_smote_pipeline("logreg", plain)
    oof_uncal = cross_val_predict(uncalibrated_pipeline, X_tr, y_tr, cv=outer_cv, method="predict_proba")[:, 1]

    # --- 2 & 3: calibrated OOF (nested CV - outer for OOF estimation, inner
    # inside CalibratedClassifierCV for its own fit/calibrate split) ---
    calibrated_pipeline = CalibratedClassifierCV(
        estimator=build_smote_pipeline("logreg", plain), method=CALIBRATION_METHOD, cv=inner_cv
    )
    oof_cal = cross_val_predict(calibrated_pipeline, X_tr, y_tr, cv=outer_cv, method="predict_proba")[:, 1]

    def summarize(name: str, proba: np.ndarray) -> dict:
        threshold = best_f1_threshold(proba, y_tr_arr)
        at_best_f1 = classification_metrics(y_tr_arr, proba, threshold)
        at_raw = classification_metrics(y_tr_arr, proba, RAW_THRESHOLD)
        mean_p = float(proba.mean())
        return {
            "model": name,
            "brier_score": float(brier_score_loss(y_tr_arr, proba)),
            "log_loss": float(log_loss(y_tr_arr, proba)),
            "roc_auc": float(roc_auc_score(y_tr_arr, proba)),
            "mean_predicted_probability": mean_p,
            "actual_prevalence": prevalence,
            "mean_predicted_over_prevalence_ratio": mean_p / prevalence,
            "best_f1_threshold": threshold,
            "at_best_f1_threshold": at_best_f1,
            "at_raw_threshold_0.550": at_raw,
        }

    summary_uncal = summarize("uncalibrated_logreg_smote", oof_uncal)
    summary_cal = summarize("calibrated_logreg_smote_sigmoid", oof_cal)

    print("\n--- A. Calibration comparison table (training-fold OOF, seed 42) ---")
    for s in (summary_uncal, summary_cal):
        print(
            f"{s['model']}: Brier={s['brier_score']:.4f} log_loss={s['log_loss']:.4f} "
            f"ROC-AUC={s['roc_auc']:.4f} mean_pred={s['mean_predicted_probability']:.4f} "
            f"ratio={s['mean_predicted_over_prevalence_ratio']:.2f}x"
        )
        print(
            f"  best-F1 threshold={s['best_f1_threshold']:.3f}: "
            f"precision={s['at_best_f1_threshold']['precision']:.3f} "
            f"recall={s['at_best_f1_threshold']['recall']:.3f} "
            f"f1={s['at_best_f1_threshold']['f1']:.3f}  "
            f"[each model's own best-F1 point - NOT the matched-recall comparison, see section E]"
        )

    # --- reliability bins ---
    bins_uncal = reliability_bins("uncalibrated_logreg_smote", oof_uncal, y_tr_arr)
    bins_cal = reliability_bins("calibrated_logreg_smote_sigmoid", oof_cal, y_tr_arr)
    print("\n--- B. Reliability-bin table (n, mean_predicted -> fraction_positive) ---")
    for label, bins_df in [("uncalibrated", bins_uncal), ("calibrated", bins_cal)]:
        print(f"  {label}:")
        for _, row in bins_df.iterrows():
            print(
                f"    bin {int(row['bin'])}: n={int(row['n']):>3} n_positive={int(row['n_positive']):>2} "
                f"predicted~{row['mean_predicted']:.3f} -> actual {row['fraction_positive']:.3f}"
            )

    bins_all = pd.concat([bins_uncal, bins_cal], ignore_index=True)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    bins_all.to_csv(ARTIFACT_DIR / "calibration_experiment.csv", index=False)

    plot_calibration_curve(bins_uncal, bins_cal, ARTIFACT_DIR / "calibration_curve.png")

    # --- 4: score distribution + F9.7 bands, calibrated OOF only ---
    dist_cal = score_distribution(oof_cal)
    bands_cal = f9_7_band_counts(oof_cal)
    print("\n--- C. Score distribution (calibrated OOF probabilities) ---")
    print(
        f"  min={dist_cal['min']:.4f} max={dist_cal['max']:.4f} mean={dist_cal['mean']:.4f} "
        f"median={dist_cal['median']:.4f} p95={dist_cal['p95']:.4f} p99={dist_cal['p99']:.4f}"
    )
    print("\n--- D. PRD F9.7 band counts (calibrated OOF probabilities, n={}) ---".format(len(oof_cal)))
    for name, stats in bands_cal.items():
        print(f"  {name}: {stats['count']} ({stats['pct']}%)")

    # --- 5: raw 0.550 vs. calibrated matched-recall threshold ---
    raw_metrics = classification_metrics(y_tr_arr, oof_uncal, RAW_THRESHOLD)
    target_recall = raw_metrics["recall"]
    cal_threshold, cal_precision, cal_recall = find_matched_recall_threshold(oof_cal, y_tr_arr, target_recall)
    cal_metrics_at_matched = classification_metrics(y_tr_arr, oof_cal, cal_threshold)
    print("\n--- E. Raw 0.550 vs. calibrated matched-recall threshold (training-fold OOF) ---")
    print(
        f"  raw threshold=0.550: precision={raw_metrics['precision']:.3f} "
        f"recall={raw_metrics['recall']:.3f} f1={raw_metrics['f1']:.3f}"
    )
    print(
        f"  calibrated threshold={cal_threshold:.3f} (searched for recall closest to "
        f"{target_recall:.3f}): precision={cal_metrics_at_matched['precision']:.3f} "
        f"recall={cal_metrics_at_matched['recall']:.3f} f1={cal_metrics_at_matched['f1']:.3f}"
    )

    # --- 6: sealed test set, calibrated candidate only, exactly once ---
    final_calibrated = CalibratedClassifierCV(
        estimator=build_smote_pipeline("logreg", plain), method=CALIBRATION_METHOD, cv=inner_cv
    )
    final_calibrated.fit(X_tr, y_tr)
    test_proba_cal = final_calibrated.predict_proba(X_te)[:, 1]
    test_metrics_at_matched = classification_metrics(y_te_arr, test_proba_cal, cal_threshold)
    test_pred_at_matched = (test_proba_cal >= cal_threshold).astype(int)
    test_cm = confusion_matrix(y_te_arr, test_pred_at_matched).tolist()
    test_summary = {
        "brier_score": float(brier_score_loss(y_te_arr, test_proba_cal)),
        "log_loss": float(log_loss(y_te_arr, test_proba_cal)),
        "roc_auc": float(roc_auc_score(y_te_arr, test_proba_cal)),
        "mean_predicted_probability": float(test_proba_cal.mean()),
        "threshold_used": cal_threshold,
        **test_metrics_at_matched,
        "confusion_matrix": test_cm,
    }
    print("\n--- F. FINAL SEALED TEST-SET CONFIRMATION (calibrated candidate, opened once) ---")
    print(f"  test set: {len(X_te)} rows, {int(y_te_arr.sum())} positive")
    print(f"  threshold used: {cal_threshold:.3f} (the matched-recall calibrated threshold from section E)")
    print(
        f"  Brier={test_summary['brier_score']:.4f} log_loss={test_summary['log_loss']:.4f} "
        f"ROC-AUC={test_summary['roc_auc']:.4f} mean_predicted={test_summary['mean_predicted_probability']:.4f}"
    )
    print(
        f"  precision={test_summary['precision']:.3f} recall={test_summary['recall']:.3f} "
        f"f1={test_summary['f1']:.3f} confusion_matrix={test_cm}"
    )
    print(
        f"  vs. OOF at the same calibrated threshold: precision={cal_metrics_at_matched['precision']:.3f} "
        f"recall={cal_metrics_at_matched['recall']:.3f} f1={cal_metrics_at_matched['f1']:.3f} "
        "(reported honestly whether this differs, not adjusted to match)"
    )

    summary_payload = {
        "calibration_method": CALIBRATION_METHOD,
        "raw_threshold": RAW_THRESHOLD,
        "training_prevalence": prevalence,
        "uncalibrated_oof": summary_uncal,
        "calibrated_oof": summary_cal,
        "score_distribution_calibrated_oof": dist_cal,
        "f9_7_bands_calibrated_oof": bands_cal,
        "matched_recall_comparison": {
            "raw_threshold": RAW_THRESHOLD,
            "raw_oof_precision": raw_metrics["precision"],
            "raw_oof_recall": raw_metrics["recall"],
            "raw_oof_f1": raw_metrics["f1"],
            "calibrated_threshold": cal_threshold,
            "calibrated_oof_precision": cal_metrics_at_matched["precision"],
            "calibrated_oof_recall": cal_metrics_at_matched["recall"],
            "calibrated_oof_f1": cal_metrics_at_matched["f1"],
        },
        "sealed_test_set_calibrated_candidate": test_summary,
    }
    with open(ARTIFACT_DIR / "calibration_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary_payload, f, indent=2)

    print(f"\nsaved calibration_experiment.csv ({len(bins_all)} rows), calibration_summary.json, "
          f"calibration_curve.png to {ARTIFACT_DIR}")


if __name__ == "__main__":
    main()
