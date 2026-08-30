"""Phase 10 follow-up: multi-seed validation of sigmoid calibration - ANALYSIS ONLY.

06_calibration.py's finding (calibrated threshold ~0.197 replaces raw 0.550,
Brier drops from ~0.171 to ~0.106) rests on one StratifiedKFold seed (42).
This script repeats that exact experiment across 4 independent seeds
(42/43/44/45) to check whether the calibrated threshold and the reliability
curve's top-bin behaviour are stable, or an artifact of one fold assignment
- before any of this becomes production-facing. Still analysis only: does
NOT change 03_train.py's SELECTED_MODEL/SELECTED_STRATEGY/
DECISION_THRESHOLD, does not touch production serving code (Phase 11 does
not exist yet), and saves no new model artifact.

Split convention, unchanged from Phase 10 throughout (03_train.py,
05_threshold_sweep.py round 2, 06_calibration.py): the OUTER 80/20
train/test split uses a single fixed random_state (42) - it is not
re-split per seed, so every seed below sees the exact same 1,176-row
training/OOF pool and the exact same sealed 294-row test set. Only the
StratifiedKFold seed (both the outer CV that produces OOF predictions and
CalibratedClassifierCV's own internal fit/calibrate split) varies across
42/43/44/45. SMOTE's random_state and the classifier's random_state both
stay fixed at 42 in every run, matching 05_threshold_sweep.py round 2's
documented convention: changing the fold assignment is the only thing
being tested.

Leakage discipline, identical to 06_calibration.py, repeated per seed:
preprocessing + SMOTE + the classifier are one imblearn.pipeline.Pipeline
(build_smote_pipeline(), imported from 06_calibration.py, in turn imported
from 05_threshold_sweep.py - no pipeline construction is duplicated here).
CalibratedClassifierCV wraps that whole pipeline as its `estimator`, so its
internal cv split refits preprocessing + SMOTE + the classifier on the
sub-training portion of each internal fold and fits the sigmoid mapping
only on that fold's held-out calibration portion - imblearn's
Pipeline.predict_proba() skips the SMOTE step at prediction/calibration
time, so the calibration portion is never resampled.
cross_val_predict then wraps that whole CalibratedClassifierCV as its own
estimator for the outer StratifiedKFold, so out-of-fold probabilities come
from genuinely nested CV: no row's own outer fold ever contributes to
fitting preprocessing, SMOTE, the classifier, or the calibration mapping
used to score it. This nesting is repeated independently for each of the 4
seeds - a seed changes both the outer and inner split's fold assignment,
nothing else.

The sealed test set is opened exactly once, at the very end, for ONE final
calibrated candidate (fit with the project's base seed, 42, matching every
other finalized Phase 10 artifact) at the ONE recommended production
threshold chosen from training/OOF evidence alone - never for calibration
or threshold selection, never per-seed.

Output: ml/attrition/artifacts/calibration_multiseed.csv (tidy long format,
one row per seed x model x reliability bin, with per-seed scalar summary
stats - Brier, log loss, ROC-AUC, mean predicted probability, prevalence,
ratio, Brier improvement, raw/calibrated matched-threshold metrics, score
distribution, and F9.7 band counts - repeated across that seed/model's bin
rows, the same merge-bins-with-summary shape 05_threshold_sweep.py round
2's calibration_comparison.csv already uses). No other artifact is written
or overwritten - 06_calibration.py's own calibration_summary.json /
calibration_experiment.csv / calibration_curve.png (the seed-42 baseline)
are left untouched; this script only imports that module, it never calls
its main().
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import brier_score_loss, confusion_matrix, log_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict, train_test_split

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
CALIBRATION_SEEDS = [42, 43, 44, 45]
FULL_DATASET_ROWS = 1470  # data/README.md's documented full-dataset row count

# 06_calibration.py's filename starts with a digit and can't be `import`ed
# normally (same constraint 02_preprocessing.py documents). Loading it reuses
# its exact pipeline builder, reliability/threshold/band helpers, and
# constants - this script introduces no new pipeline or metric logic beyond
# looping the existing seed-42 experiment across 4 seeds.
_CAL_PATH = Path(__file__).resolve().parent / "06_calibration.py"
_spec = importlib.util.spec_from_file_location("attrition_calibration", _CAL_PATH)
_cal = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cal)

_train = _cal._train
RANDOM_STATE = _cal.RANDOM_STATE  # 42 - the OUTER 80/20 split seed, fixed, never varies
TEST_SIZE = _cal.TEST_SIZE
N_SPLITS = _cal.N_SPLITS
CALIBRATION_METHOD = _cal.CALIBRATION_METHOD
RAW_THRESHOLD = _cal.RAW_THRESHOLD
build_smote_pipeline = _cal.build_smote_pipeline
reliability_bins = _cal.reliability_bins
classification_metrics = _cal.classification_metrics
find_matched_recall_threshold = _cal.find_matched_recall_threshold
score_distribution = _cal.score_distribution
f9_7_band_counts = _cal.f9_7_band_counts


def run_one_seed(seed: int, X_tr: pd.DataFrame, y_tr: pd.Series, y_tr_arr: np.ndarray, plain: dict, prevalence: float) -> dict:
    """Repeats 06_calibration.py's seed-42 experiment at one StratifiedKFold seed."""
    outer_cv = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=seed)
    inner_cv = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=seed)

    uncalibrated_pipeline = build_smote_pipeline("logreg", plain)
    oof_uncal = cross_val_predict(uncalibrated_pipeline, X_tr, y_tr, cv=outer_cv, method="predict_proba")[:, 1]

    calibrated_pipeline = CalibratedClassifierCV(
        estimator=build_smote_pipeline("logreg", plain), method=CALIBRATION_METHOD, cv=inner_cv
    )
    oof_cal = cross_val_predict(calibrated_pipeline, X_tr, y_tr, cv=outer_cv, method="predict_proba")[:, 1]

    brier_uncal = float(brier_score_loss(y_tr_arr, oof_uncal))
    brier_cal = float(brier_score_loss(y_tr_arr, oof_cal))
    logloss_uncal = float(log_loss(y_tr_arr, oof_uncal))
    logloss_cal = float(log_loss(y_tr_arr, oof_cal))

    # Threshold validation: raw 0.550 on the uncalibrated model, then the
    # calibrated threshold that reproduces the SAME OOF recall - found by
    # searching the calibrated model's own precision-recall curve, never by
    # transforming 0.550 mathematically.
    raw_metrics = classification_metrics(y_tr_arr, oof_uncal, RAW_THRESHOLD)
    target_recall = raw_metrics["recall"]
    cal_threshold, _, _ = find_matched_recall_threshold(oof_cal, y_tr_arr, target_recall)
    cal_metrics = classification_metrics(y_tr_arr, oof_cal, cal_threshold)

    return {
        "seed": seed,
        "oof_uncal": oof_uncal,
        "oof_cal": oof_cal,
        "brier_uncal": brier_uncal,
        "brier_cal": brier_cal,
        "brier_improvement": brier_uncal - brier_cal,
        "logloss_uncal": logloss_uncal,
        "logloss_cal": logloss_cal,
        "logloss_improvement": logloss_uncal - logloss_cal,
        "roc_auc_uncal": float(roc_auc_score(y_tr_arr, oof_uncal)),
        "roc_auc_cal": float(roc_auc_score(y_tr_arr, oof_cal)),
        "mean_pred_uncal": float(oof_uncal.mean()),
        "mean_pred_cal": float(oof_cal.mean()),
        "prevalence": prevalence,
        "ratio_uncal": float(oof_uncal.mean() / prevalence),
        "ratio_cal": float(oof_cal.mean() / prevalence),
        "raw_metrics": raw_metrics,
        "cal_threshold": cal_threshold,
        "cal_metrics": cal_metrics,
        "dist_cal": score_distribution(oof_cal),
        "bands_cal": f9_7_band_counts(oof_cal),
        "bins_uncal": reliability_bins("uncalibrated_logreg_smote", oof_uncal, y_tr_arr),
        "bins_cal": reliability_bins("calibrated_logreg_smote_sigmoid", oof_cal, y_tr_arr),
    }


def build_multiseed_table(results: list[dict]) -> pd.DataFrame:
    """One row per (seed, model, reliability bin) - calibration_comparison.csv's
    existing merge-bins-with-summary shape, extended across 4 seeds."""
    rows = []
    for r in results:
        for model_label, bins_df, is_cal in [
            ("uncalibrated_logreg_smote", r["bins_uncal"], False),
            ("calibrated_logreg_smote_sigmoid", r["bins_cal"], True),
        ]:
            for _, b in bins_df.iterrows():
                rows.append(
                    {
                        "seed": r["seed"],
                        "model": model_label,
                        "bin": int(b["bin"]),
                        "bin_n": int(b["n"]),
                        "bin_n_positive": int(b["n_positive"]),
                        "bin_mean_predicted": float(b["mean_predicted"]),
                        "bin_fraction_positive": float(b["fraction_positive"]),
                        "calibration_gap": float(b["fraction_positive"] - b["mean_predicted"]),
                        "brier_score": r["brier_cal"] if is_cal else r["brier_uncal"],
                        "log_loss": r["logloss_cal"] if is_cal else r["logloss_uncal"],
                        "roc_auc": r["roc_auc_cal"] if is_cal else r["roc_auc_uncal"],
                        "mean_predicted_probability": r["mean_pred_cal"] if is_cal else r["mean_pred_uncal"],
                        "actual_prevalence": r["prevalence"],
                        "mean_pred_over_prevalence_ratio": r["ratio_cal"] if is_cal else r["ratio_uncal"],
                        "brier_improvement_vs_uncalibrated": r["brier_improvement"],
                        "raw_threshold": RAW_THRESHOLD,
                        "raw_threshold_precision": r["raw_metrics"]["precision"],
                        "raw_threshold_recall": r["raw_metrics"]["recall"],
                        "raw_threshold_f1": r["raw_metrics"]["f1"],
                        "calibrated_matched_threshold": r["cal_threshold"] if is_cal else np.nan,
                        "calibrated_matched_precision": r["cal_metrics"]["precision"] if is_cal else np.nan,
                        "calibrated_matched_recall": r["cal_metrics"]["recall"] if is_cal else np.nan,
                        "calibrated_matched_f1": r["cal_metrics"]["f1"] if is_cal else np.nan,
                        "score_min": r["dist_cal"]["min"] if is_cal else np.nan,
                        "score_max": r["dist_cal"]["max"] if is_cal else np.nan,
                        "score_median": r["dist_cal"]["median"] if is_cal else np.nan,
                        "score_p95": r["dist_cal"]["p95"] if is_cal else np.nan,
                        "score_p99": r["dist_cal"]["p99"] if is_cal else np.nan,
                        "f9_7_low_count": r["bands_cal"]["low_lt_30"]["count"] if is_cal else np.nan,
                        "f9_7_low_pct": r["bands_cal"]["low_lt_30"]["pct"] if is_cal else np.nan,
                        "f9_7_medium_count": r["bands_cal"]["medium_30_60"]["count"] if is_cal else np.nan,
                        "f9_7_medium_pct": r["bands_cal"]["medium_30_60"]["pct"] if is_cal else np.nan,
                        "f9_7_high_count": r["bands_cal"]["high_gt_60"]["count"] if is_cal else np.nan,
                        "f9_7_high_pct": r["bands_cal"]["high_gt_60"]["pct"] if is_cal else np.nan,
                        "f9_7_high_count_full_dataset_approx": (
                            round(r["bands_cal"]["high_gt_60"]["pct"] / 100 * FULL_DATASET_ROWS) if is_cal else np.nan
                        ),
                    }
                )
    return pd.DataFrame(rows)


def recommend_threshold(results: list[dict], y_tr_arr: np.ndarray) -> dict:
    """Evidence-based pick among mean/median/seed-42 calibrated thresholds:
    cross-apply each candidate to EVERY seed's own OOF calibrated
    probabilities and compare the resulting recall's closeness to the
    raw-0.550 recall target and its stability across seeds - not just how
    close the three threshold values are to each other."""
    thresholds = {r["seed"]: r["cal_threshold"] for r in results}
    values = list(thresholds.values())
    mean_t = float(np.mean(values))
    median_t = float(np.median(values))
    seed42_t = thresholds[42]
    target_recall_mean = float(np.mean([r["raw_metrics"]["recall"] for r in results]))

    oof_cal_by_seed = {r["seed"]: r["oof_cal"] for r in results}
    candidates = {"mean": mean_t, "median": median_t, "seed_42": seed42_t}

    cross_rows = []
    for cand_name, t in candidates.items():
        for seed, oof_cal in oof_cal_by_seed.items():
            m = classification_metrics(y_tr_arr, oof_cal, t)
            cross_rows.append({"candidate": cand_name, "threshold": t, "seed": seed, **m})
    cross_df = pd.DataFrame(cross_rows)

    agg = (
        cross_df.groupby("candidate")
        .agg(
            threshold=("threshold", "first"),
            recall_mean=("recall", "mean"),
            recall_std=("recall", "std"),
            precision_mean=("precision", "mean"),
            precision_std=("precision", "std"),
            f1_mean=("f1", "mean"),
            f1_std=("f1", "std"),
        )
        .reset_index()
    )
    agg["recall_gap_from_target"] = (agg["recall_mean"] - target_recall_mean).abs()
    agg = agg.sort_values("recall_gap_from_target").reset_index(drop=True)
    recommended_name = agg.iloc[0]["candidate"]

    return {
        "thresholds_by_seed": thresholds,
        "mean_threshold": mean_t,
        "median_threshold": median_t,
        "seed_42_threshold": seed42_t,
        "target_recall_mean": target_recall_mean,
        "cross_apply_table": cross_df,
        "candidate_summary": agg,
        "recommended_name": recommended_name,
        "recommended_threshold": float(candidates[recommended_name]),
    }


def final_sealed_test_evaluation(
    X_tr: pd.DataFrame, y_tr: pd.Series, X_te: pd.DataFrame, y_te_arr: np.ndarray, plain: dict, threshold: float
) -> dict:
    """The ONE calibrated candidate evaluated ONCE on the sealed test set, fit
    with the project's base seed (42) - the only seed anything gets shipped
    under - at the one production threshold fixed by training/OOF evidence."""
    inner_cv = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)
    final_calibrated = CalibratedClassifierCV(
        estimator=build_smote_pipeline("logreg", plain), method=CALIBRATION_METHOD, cv=inner_cv
    )
    final_calibrated.fit(X_tr, y_tr)
    test_proba = final_calibrated.predict_proba(X_te)[:, 1]
    metrics = classification_metrics(y_te_arr, test_proba, threshold)
    pred = (test_proba >= threshold).astype(int)
    cm = confusion_matrix(y_te_arr, pred).tolist()
    return {
        "brier_score": float(brier_score_loss(y_te_arr, test_proba)),
        "log_loss": float(log_loss(y_te_arr, test_proba)),
        "roc_auc": float(roc_auc_score(y_te_arr, test_proba)),
        "mean_predicted_probability": float(test_proba.mean()),
        "threshold_used": threshold,
        **metrics,
        "confusion_matrix": cm,
        "n_test": int(len(y_te_arr)),
        "n_test_positive": int(y_te_arr.sum()),
    }


def main() -> None:
    print("=" * 78)
    print("Phase 10 multi-seed calibration validation - ANALYSIS ONLY, not production.")
    print(f"Seeds: {CALIBRATION_SEEDS}  |  Calibration method: {CALIBRATION_METHOD}")
    print("Outer 80/20 split is FIXED at random_state=42 for every seed below -")
    print("only the StratifiedKFold fold-assignment seed varies. Sealed test set")
    print("is opened exactly once, at the very end, for one final candidate only.")
    print("=" * 78)

    X, y = _train.load_and_clean(_train.DATA_PATH)
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=TEST_SIZE, stratify=y, random_state=RANDOM_STATE)
    y_tr_arr = np.asarray(y_tr)
    y_te_arr = np.asarray(y_te)
    prevalence = float(y_tr_arr.mean())
    print(f"\ntrain/OOF pool: {len(X_tr)} rows, {int(y_tr_arr.sum())} positive (prevalence={prevalence:.4f})")
    print(f"sealed test set: {len(X_te)} rows, {int(y_te_arr.sum())} positive (untouched until section F)")

    plain = _train.build_plain_estimators()
    results = [run_one_seed(seed, X_tr, y_tr, y_tr_arr, plain, prevalence) for seed in CALIBRATION_SEEDS]

    # --- A: per-seed calibration comparison table ---
    print("\n" + "=" * 78 + "\nA. FOUR-SEED CALIBRATION RESULTS\n" + "=" * 78)
    for r in results:
        print(f"\n--- seed {r['seed']} ---")
        print(
            f"  uncalibrated: Brier={r['brier_uncal']:.4f} log_loss={r['logloss_uncal']:.4f} "
            f"ROC-AUC={r['roc_auc_uncal']:.4f} mean_pred={r['mean_pred_uncal']:.4f} ratio={r['ratio_uncal']:.2f}x"
        )
        print(
            f"  calibrated:   Brier={r['brier_cal']:.4f} log_loss={r['logloss_cal']:.4f} "
            f"ROC-AUC={r['roc_auc_cal']:.4f} mean_pred={r['mean_pred_cal']:.4f} ratio={r['ratio_cal']:.2f}x"
        )
        print(
            f"  calibration improvement: Brier -{r['brier_improvement']:.4f}  log_loss -{r['logloss_improvement']:.4f}"
        )
        d = r["dist_cal"]
        print(
            f"  calibrated score distribution: min={d['min']:.4f} median={d['median']:.4f} "
            f"p95={d['p95']:.4f} p99={d['p99']:.4f} max={d['max']:.4f}"
        )
        b = r["bands_cal"]
        n_oof = len(r["oof_cal"])
        high_full = round(b["high_gt_60"]["pct"] / 100 * FULL_DATASET_ROWS)
        print(
            f"  F9.7 bands (n={n_oof} OOF): Low={b['low_lt_30']['count']} ({b['low_lt_30']['pct']}%)  "
            f"Medium={b['medium_30_60']['count']} ({b['medium_30_60']['pct']}%)  "
            f"High={b['high_gt_60']['count']} ({b['high_gt_60']['pct']}%)"
        )
        print(f"  High band, projected to full {FULL_DATASET_ROWS}-row dataset (approx.): ~{high_full} employees")
        print("  reliability bins (calibrated), n / n_positive / predicted -> actual:")
        for _, row in r["bins_cal"].iterrows():
            print(
                f"    bin {int(row['bin'])}: n={int(row['n']):>3} n_positive={int(row['n_positive']):>2} "
                f"predicted~{row['mean_predicted']:.3f} -> actual {row['fraction_positive']:.3f}"
            )

    # --- B: Brier comparison summary ---
    brier_improvements = [r["brier_improvement"] for r in results]
    print("\n" + "=" * 78 + "\nB. BRIER COMPARISON\n" + "=" * 78)
    for r in results:
        print(f"  seed {r['seed']}: uncalibrated={r['brier_uncal']:.4f}  calibrated={r['brier_cal']:.4f}  improvement={r['brier_improvement']:.4f}")
    print(f"  mean improvement={np.mean(brier_improvements):.4f}  std={np.std(brier_improvements):.4f}")

    # --- C: top-bin stability ---
    print("\n" + "=" * 78 + "\nC. TOP-BIN STABILITY (calibrated model, highest reliability bin)\n" + "=" * 78)
    top_bin_rows = []
    for r in results:
        top = r["bins_cal"].iloc[-1]
        gap = float(top["fraction_positive"] - top["mean_predicted"])
        direction = "UNDER-prediction (actual > predicted)" if gap > 0 else "OVER-prediction (predicted > actual)"
        top_bin_rows.append(
            {"seed": r["seed"], "n": int(top["n"]), "mean_predicted": float(top["mean_predicted"]),
             "fraction_positive": float(top["fraction_positive"]), "gap": gap, "direction": direction}
        )
        print(
            f"  seed {r['seed']}: n={int(top['n'])} mean_predicted={top['mean_predicted']:.4f} "
            f"fraction_positive={top['fraction_positive']:.4f} gap={gap:+.4f}  {direction}"
        )
    signs = [1 if row["gap"] > 0 else -1 for row in top_bin_rows]
    consistent = len(set(signs)) == 1
    print(f"\n  direction consistent across all {len(results)} seeds: {consistent}")

    # --- D: threshold validation ---
    print("\n" + "=" * 78 + "\nD. THRESHOLD VALIDATION\n" + "=" * 78)
    for r in results:
        rm, cm = r["raw_metrics"], r["cal_metrics"]
        print(
            f"  seed {r['seed']}: raw(0.550) P={rm['precision']:.3f} R={rm['recall']:.3f} F1={rm['f1']:.3f}  |  "
            f"calibrated({r['cal_threshold']:.3f}) P={cm['precision']:.3f} R={cm['recall']:.3f} F1={cm['f1']:.3f}"
        )
    recalls_at_own_t = [r["cal_metrics"]["recall"] for r in results]
    precisions_at_own_t = [r["cal_metrics"]["precision"] for r in results]
    f1s_at_own_t = [r["cal_metrics"]["f1"] for r in results]
    print(
        f"\n  operating-point stability at each seed's OWN matched threshold: "
        f"recall mean={np.mean(recalls_at_own_t):.3f} std={np.std(recalls_at_own_t):.4f}  "
        f"precision mean={np.mean(precisions_at_own_t):.3f} std={np.std(precisions_at_own_t):.4f}  "
        f"F1 mean={np.mean(f1s_at_own_t):.3f} std={np.std(f1s_at_own_t):.4f}"
    )

    # --- E: threshold adoption recommendation ---
    print("\n" + "=" * 78 + "\nE. THRESHOLD ADOPTION RECOMMENDATION\n" + "=" * 78)
    rec = recommend_threshold(results, y_tr_arr)
    print(f"  per-seed calibrated thresholds: {rec['thresholds_by_seed']}")
    print(f"  mean={rec['mean_threshold']:.4f}  median={rec['median_threshold']:.4f}  seed_42={rec['seed_42_threshold']:.4f}")
    print(f"  target recall (mean of raw-0.550 recall across seeds): {rec['target_recall_mean']:.4f}")
    print("\n  candidate threshold cross-applied to EVERY seed's own OOF calibrated probabilities:")
    print(rec["candidate_summary"].to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print(f"\n  RECOMMENDED: {rec['recommended_name']} = {rec['recommended_threshold']:.4f}")

    # --- F: sealed test set, final calibrated candidate, exactly once ---
    print("\n" + "=" * 78 + "\nF. FINAL SEALED TEST-SET CONFIRMATION\n" + "=" * 78)
    test_summary = final_sealed_test_evaluation(X_tr, y_tr, X_te, y_te_arr, plain, rec["recommended_threshold"])
    print(f"  test set: {test_summary['n_test']} rows, {test_summary['n_test_positive']} positive")
    print(f"  threshold used: {test_summary['threshold_used']:.4f} ({rec['recommended_name']}, fixed before this evaluation)")
    print(
        f"  Brier={test_summary['brier_score']:.4f} log_loss={test_summary['log_loss']:.4f} "
        f"ROC-AUC={test_summary['roc_auc']:.4f} mean_predicted={test_summary['mean_predicted_probability']:.4f}"
    )
    print(
        f"  precision={test_summary['precision']:.3f} recall={test_summary['recall']:.3f} "
        f"f1={test_summary['f1']:.3f} confusion_matrix={test_summary['confusion_matrix']}"
    )

    # --- write the one requested artifact ---
    multiseed_df = build_multiseed_table(results)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ARTIFACT_DIR / "calibration_multiseed.csv"
    multiseed_df.to_csv(out_path, index=False)
    print(f"\nsaved {len(multiseed_df)} rows to {out_path}")

    # Machine-readable echo of the recommendation + sealed-test result, for
    # this turn's report only - not a new artifact file (none requested
    # beyond calibration_multiseed.csv).
    print("\n--- JSON echo (report use only, not saved to disk) ---")
    print(
        json.dumps(
            {
                "recommended_threshold_name": rec["recommended_name"],
                "recommended_threshold": rec["recommended_threshold"],
                "thresholds_by_seed": rec["thresholds_by_seed"],
                "sealed_test_set": test_summary,
                "top_bin_direction_consistent": consistent,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
