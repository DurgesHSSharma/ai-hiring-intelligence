"""Phase 10 follow-up: sigmoid vs. isotonic calibration - ANALYSIS ONLY.

07_calibration_multiseed.py confirmed sigmoid calibration is stable across 4
seeds (large, consistent Brier improvement; mean predicted probability near
true prevalence; ROC-AUC essentially unchanged; matched-recall threshold
stable in [0.193, 0.211]) but found one consistent, seed-independent
limitation: the highest calibration bin under-predicts risk by ~12-15
percentage points in every seed. This script tests whether isotonic
calibration (a non-parametric, higher-capacity monotonic fit - the
alternative 06_calibration.py's own docstring named and explicitly declined
in favour of sigmoid, on the grounds that ~190 training positives is thin
for isotonic's much larger effective parameter count) materially closes that
specific tail gap without trading away what sigmoid already earned. Still
analysis only: does not change 03_train.py's SELECTED_MODEL/
SELECTED_STRATEGY/DECISION_THRESHOLD, does not touch production serving code
(Phase 11 does not exist yet), saves no new model artifact.

Everything held fixed from 07_calibration_multiseed.py's setup, unchanged
here: Logistic Regression, SMOTE, preprocessing, the outer 80/20 split
(random_state=42, never re-split per seed), the sealed 294-row test set, and
the 4 StratifiedKFold seeds (42/43/44/45). The only new axis is the
calibration `method` argument to CalibratedClassifierCV - "sigmoid" (already
validated) vs. "isotonic" (tested here for the first time), compared at each
of the same 4 seeds, on the exact same per-seed outer fold assignment (both
methods reuse the same StratifiedKFold(seed) instance construction, so their
OOF splits are identical within a seed - only the calibration mapping
differs).

Leakage discipline, identical to 06_calibration.py and
07_calibration_multiseed.py, repeated per (seed, method): preprocessing +
SMOTE + the classifier are one imblearn.pipeline.Pipeline
(build_smote_pipeline(), imported from 06_calibration.py - no pipeline
construction is duplicated here). CalibratedClassifierCV wraps that whole
pipeline as its `estimator`; its internal cv (StratifiedKFold(seed)) refits
preprocessing + SMOTE + the classifier on the sub-training portion of each
inner fold and fits the calibration mapping (sigmoid or isotonic) only on
that fold's held-out calibration portion - imblearn's Pipeline.predict_proba
skips the SMOTE step at prediction/calibration time, so the calibration
portion is never resampled. The outer StratifiedKFold(seed) then drives
cross_val_predict, so no row's own outer fold ever contributes to fitting
preprocessing, SMOTE, the classifier, or the calibration mapping used to
score it - true of both methods, independently, at every seed.

The sealed test set is opened exactly once, at the very end, for ONE
calibration method (whichever this run's evidence selects) at ONE threshold
fixed from training/OOF evidence alone - never for method selection, never
for threshold selection.

Output: ml/attrition/artifacts/calibration_method_comparison.csv (tidy long
format, one row per seed x method x reliability bin, with per-seed-method
scalar summary stats - Brier, log loss, ROC-AUC, mean predicted probability,
prevalence, ratio, Brier improvement over the shared uncalibrated baseline,
score distribution, F9.7 band counts, matched-threshold precision/recall/F1
- repeated across that seed/method's bin rows, the same merge-bins-with-
summary shape calibration_comparison.csv and calibration_multiseed.csv
already use). No other artifact is written or overwritten.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import brier_score_loss, confusion_matrix, log_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict, train_test_split

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
CALIBRATION_SEEDS = [42, 43, 44, 45]
CALIBRATION_METHODS = ["sigmoid", "isotonic"]
FULL_DATASET_ROWS = 1470

# The sigmoid threshold 07_calibration_multiseed.py's section E recommended
# and the sealed test set already confirmed. Reused as-is if sigmoid remains
# the selected method here - never recomputed from this run's data.
SIGMOID_PRODUCTION_THRESHOLD = 0.2005

# 06_calibration.py's filename starts with a digit and can't be `import`ed
# normally (same constraint 02_preprocessing.py documents). Loading it reuses
# its exact pipeline builder, reliability/threshold/band helpers, and
# constants - no pipeline or metric logic is duplicated here.
_CAL_PATH = Path(__file__).resolve().parent / "06_calibration.py"
_spec = importlib.util.spec_from_file_location("attrition_calibration", _CAL_PATH)
_cal = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cal)

_train = _cal._train
RANDOM_STATE = _cal.RANDOM_STATE  # 42 - the OUTER 80/20 split seed, fixed, never varies
TEST_SIZE = _cal.TEST_SIZE
N_SPLITS = _cal.N_SPLITS
RAW_THRESHOLD = _cal.RAW_THRESHOLD
build_smote_pipeline = _cal.build_smote_pipeline
reliability_bins = _cal.reliability_bins
classification_metrics = _cal.classification_metrics
find_matched_recall_threshold = _cal.find_matched_recall_threshold
score_distribution = _cal.score_distribution
f9_7_band_counts = _cal.f9_7_band_counts


def run_one_seed_method(seed: int, method: str, X_tr, y_tr, y_tr_arr: np.ndarray, plain: dict, oof_uncal: np.ndarray) -> dict:
    """One (seed, calibration method) cell. oof_uncal is passed in, computed
    once per seed and shared across both methods - it does not depend on the
    calibration method, only on the seed's outer fold assignment."""
    outer_cv = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=seed)
    inner_cv = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=seed)

    calibrated_pipeline = CalibratedClassifierCV(
        estimator=build_smote_pipeline("logreg", plain), method=method, cv=inner_cv
    )
    oof_cal = cross_val_predict(calibrated_pipeline, X_tr, y_tr, cv=outer_cv, method="predict_proba")[:, 1]

    brier_cal = float(brier_score_loss(y_tr_arr, oof_cal))
    brier_uncal = float(brier_score_loss(y_tr_arr, oof_uncal))
    prevalence = float(y_tr_arr.mean())

    raw_metrics = classification_metrics(y_tr_arr, oof_uncal, RAW_THRESHOLD)
    target_recall = raw_metrics["recall"]
    cal_threshold, _, _ = find_matched_recall_threshold(oof_cal, y_tr_arr, target_recall)
    cal_metrics = classification_metrics(y_tr_arr, oof_cal, cal_threshold)

    bins_cal = reliability_bins(f"logreg_smote_{method}", oof_cal, y_tr_arr)

    return {
        "seed": seed,
        "method": method,
        "oof_cal": oof_cal,
        "brier_cal": brier_cal,
        "brier_uncal": brier_uncal,
        "brier_improvement": brier_uncal - brier_cal,
        "logloss_cal": float(log_loss(y_tr_arr, oof_cal)),
        "roc_auc_cal": float(roc_auc_score(y_tr_arr, oof_cal)),
        "mean_pred_cal": float(oof_cal.mean()),
        "prevalence": prevalence,
        "ratio_cal": float(oof_cal.mean() / prevalence),
        "raw_metrics": raw_metrics,
        "cal_threshold": cal_threshold,
        "cal_metrics": cal_metrics,
        "dist_cal": score_distribution(oof_cal),
        "bands_cal": f9_7_band_counts(oof_cal),
        "bins_cal": bins_cal,
        "n_bins_actual": len(bins_cal),
    }


def build_comparison_table(results: list[dict]) -> pd.DataFrame:
    """One row per (seed, method, reliability bin) - calibration_comparison.csv's
    / calibration_multiseed.csv's existing merge-bins-with-summary shape."""
    rows = []
    for r in results:
        for _, b in r["bins_cal"].iterrows():
            rows.append(
                {
                    "seed": r["seed"],
                    "method": r["method"],
                    "bin": int(b["bin"]),
                    "bin_n": int(b["n"]),
                    "bin_n_positive": int(b["n_positive"]),
                    "bin_mean_predicted": float(b["mean_predicted"]),
                    "bin_fraction_positive": float(b["fraction_positive"]),
                    "calibration_gap": float(b["fraction_positive"] - b["mean_predicted"]),
                    "brier_score": r["brier_cal"],
                    "brier_uncalibrated_baseline": r["brier_uncal"],
                    "brier_improvement_vs_uncalibrated": r["brier_improvement"],
                    "log_loss": r["logloss_cal"],
                    "roc_auc": r["roc_auc_cal"],
                    "mean_predicted_probability": r["mean_pred_cal"],
                    "actual_prevalence": r["prevalence"],
                    "mean_pred_over_prevalence_ratio": r["ratio_cal"],
                    "score_min": r["dist_cal"]["min"],
                    "score_median": r["dist_cal"]["median"],
                    "score_p95": r["dist_cal"]["p95"],
                    "score_p99": r["dist_cal"]["p99"],
                    "score_max": r["dist_cal"]["max"],
                    "f9_7_low_count": r["bands_cal"]["low_lt_30"]["count"],
                    "f9_7_low_pct": r["bands_cal"]["low_lt_30"]["pct"],
                    "f9_7_medium_count": r["bands_cal"]["medium_30_60"]["count"],
                    "f9_7_medium_pct": r["bands_cal"]["medium_30_60"]["pct"],
                    "f9_7_high_count": r["bands_cal"]["high_gt_60"]["count"],
                    "f9_7_high_pct": r["bands_cal"]["high_gt_60"]["pct"],
                    "matched_threshold": r["cal_threshold"],
                    "matched_precision": r["cal_metrics"]["precision"],
                    "matched_recall": r["cal_metrics"]["recall"],
                    "matched_f1": r["cal_metrics"]["f1"],
                }
            )
    return pd.DataFrame(rows)


def recommend_threshold_for_method(seed_results: list[dict], y_tr_arr: np.ndarray) -> dict:
    """Same evidence-based mean/median/seed-42 cross-apply procedure
    07_calibration_multiseed.py's section E used for sigmoid, generalised to
    whichever method is passed in."""
    thresholds = {r["seed"]: r["cal_threshold"] for r in seed_results}
    values = list(thresholds.values())
    mean_t = float(np.mean(values))
    median_t = float(np.median(values))
    seed42_t = thresholds[42]
    target_recall_mean = float(np.mean([r["raw_metrics"]["recall"] for r in seed_results]))
    oof_cal_by_seed = {r["seed"]: r["oof_cal"] for r in seed_results}
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
        "candidate_summary": agg,
        "recommended_name": recommended_name,
        "recommended_threshold": float(candidates[recommended_name]),
    }


def final_sealed_test_evaluation(X_tr, y_tr, X_te, y_te_arr: np.ndarray, plain: dict, method: str, threshold: float) -> dict:
    """The ONE selected calibration method evaluated ONCE on the sealed test
    set, fit with the project's base seed (42), at the ONE threshold already
    fixed from training/OOF evidence."""
    inner_cv = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)
    final_calibrated = CalibratedClassifierCV(
        estimator=build_smote_pipeline("logreg", plain), method=method, cv=inner_cv
    )
    final_calibrated.fit(X_tr, y_tr)
    test_proba = final_calibrated.predict_proba(X_te)[:, 1]
    metrics = classification_metrics(y_te_arr, test_proba, threshold)
    pred = (test_proba >= threshold).astype(int)
    cm = confusion_matrix(y_te_arr, pred).tolist()
    return {
        "method": method,
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
    print("Phase 10 follow-up: sigmoid vs. isotonic calibration - ANALYSIS ONLY.")
    print(f"Seeds: {CALIBRATION_SEEDS}  |  Methods: {CALIBRATION_METHODS}")
    print("Outer 80/20 split fixed at random_state=42 for every seed/method below.")
    print("Sealed test set opened exactly once, at the end, for the SELECTED method only.")
    print("=" * 78)

    X, y = _train.load_and_clean(_train.DATA_PATH)
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=TEST_SIZE, stratify=y, random_state=RANDOM_STATE)
    y_tr_arr = np.asarray(y_tr)
    y_te_arr = np.asarray(y_te)
    print(f"\ntrain/OOF pool: {len(X_tr)} rows, {int(y_tr_arr.sum())} positive")
    print(f"sealed test set: {len(X_te)} rows, {int(y_te_arr.sum())} positive (untouched until the final section)")

    plain = _train.build_plain_estimators()

    # Uncalibrated OOF is shared by both methods within a seed (same outer
    # fold assignment, same pipeline) - computed once per seed, not twice.
    oof_uncal_by_seed: dict[int, np.ndarray] = {}
    for seed in CALIBRATION_SEEDS:
        outer_cv = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=seed)
        uncalibrated_pipeline = build_smote_pipeline("logreg", plain)
        oof_uncal_by_seed[seed] = cross_val_predict(
            uncalibrated_pipeline, X_tr, y_tr, cv=outer_cv, method="predict_proba"
        )[:, 1]

    results: dict[str, list[dict]] = {m: [] for m in CALIBRATION_METHODS}
    for seed in CALIBRATION_SEEDS:
        for method in CALIBRATION_METHODS:
            results[method].append(
                run_one_seed_method(seed, method, X_tr, y_tr, y_tr_arr, plain, oof_uncal_by_seed[seed])
            )

    # --- 1: four-seed sigmoid vs. isotonic table ---
    print("\n" + "=" * 78 + "\n1. FOUR-SEED SIGMOID VS. ISOTONIC TABLE\n" + "=" * 78)
    for seed in CALIBRATION_SEEDS:
        print(f"\n--- seed {seed} ---")
        for method in CALIBRATION_METHODS:
            r = next(x for x in results[method] if x["seed"] == seed)
            print(
                f"  {method:>8}: Brier={r['brier_cal']:.4f} log_loss={r['logloss_cal']:.4f} "
                f"ROC-AUC={r['roc_auc_cal']:.4f} mean_pred={r['mean_pred_cal']:.4f} "
                f"prevalence={r['prevalence']:.4f} ratio={r['ratio_cal']:.2f}x  "
                f"(n_bins_actual={r['n_bins_actual']})"
            )

    # --- 2 & 3: Brier improvements, cross-seed mean/std ---
    print("\n" + "=" * 78 + "\n2/3. BRIER IMPROVEMENTS (vs. shared uncalibrated baseline)\n" + "=" * 78)
    brier_stats = {}
    for method in CALIBRATION_METHODS:
        improvements = [r["brier_improvement"] for r in results[method]]
        briers = [r["brier_cal"] for r in results[method]]
        for r in results[method]:
            print(f"  {method:>8} seed {r['seed']}: Brier={r['brier_cal']:.4f} improvement={r['brier_improvement']:.4f}")
        brier_stats[method] = {
            "improvement_mean": float(np.mean(improvements)),
            "improvement_std": float(np.std(improvements)),
            "brier_mean": float(np.mean(briers)),
            "brier_std": float(np.std(briers)),
        }
        print(
            f"  {method:>8} cross-seed: Brier mean={brier_stats[method]['brier_mean']:.4f} "
            f"std={brier_stats[method]['brier_std']:.4f}  |  improvement mean={brier_stats[method]['improvement_mean']:.4f} "
            f"std={brier_stats[method]['improvement_std']:.4f}"
        )

    # --- 4: top-bin comparison ---
    print("\n" + "=" * 78 + "\n4. TOP-BIN COMPARISON\n" + "=" * 78)
    top_bin_stats = {method: [] for method in CALIBRATION_METHODS}
    for method in CALIBRATION_METHODS:
        for r in results[method]:
            top = r["bins_cal"].iloc[-1]
            gap = float(top["fraction_positive"] - top["mean_predicted"])
            direction = "UNDER" if gap > 0 else "OVER"
            top_bin_stats[method].append(gap)
            print(
                f"  {method:>8} seed {r['seed']}: n={int(top['n'])} mean_predicted={top['mean_predicted']:.4f} "
                f"fraction_positive={top['fraction_positive']:.4f} gap={gap:+.4f} ({direction}-prediction)"
            )
    for method in CALIBRATION_METHODS:
        gaps = top_bin_stats[method]
        print(f"  {method:>8} top-bin gap: mean={np.mean(gaps):+.4f} std={np.std(gaps):.4f} |mean|={np.mean(np.abs(gaps)):.4f}")

    # --- 5: next-highest bin comparison ---
    print("\n" + "=" * 78 + "\n5. NEXT-HIGHEST-BIN COMPARISON\n" + "=" * 78)
    for method in CALIBRATION_METHODS:
        for r in results[method]:
            bins_df = r["bins_cal"]
            if len(bins_df) < 2:
                print(f"  {method:>8} seed {r['seed']}: fewer than 2 bins (n_bins_actual={len(bins_df)}) - skipped")
                continue
            nxt = bins_df.iloc[-2]
            gap = float(nxt["fraction_positive"] - nxt["mean_predicted"])
            direction = "UNDER" if gap > 0 else "OVER"
            print(
                f"  {method:>8} seed {r['seed']}: n={int(nxt['n'])} mean_predicted={nxt['mean_predicted']:.4f} "
                f"fraction_positive={nxt['fraction_positive']:.4f} gap={gap:+.4f} ({direction}-prediction)"
            )

    # --- 6: score distributions + F9.7 bands ---
    print("\n" + "=" * 78 + "\n6. SCORE DISTRIBUTIONS AND F9.7 BAND COUNTS\n" + "=" * 78)
    for method in CALIBRATION_METHODS:
        for r in results[method]:
            d, b = r["dist_cal"], r["bands_cal"]
            print(
                f"  {method:>8} seed {r['seed']}: min={d['min']:.4f} median={d['median']:.4f} "
                f"p95={d['p95']:.4f} p99={d['p99']:.4f} max={d['max']:.4f}"
            )
            print(
                f"           F9.7: Low={b['low_lt_30']['count']} ({b['low_lt_30']['pct']}%)  "
                f"Medium={b['medium_30_60']['count']} ({b['medium_30_60']['pct']}%)  "
                f"High={b['high_gt_60']['count']} ({b['high_gt_60']['pct']}%)"
            )

    # --- 7: matched-recall threshold comparison ---
    print("\n" + "=" * 78 + "\n7. MATCHED-RECALL THRESHOLD COMPARISON\n" + "=" * 78)
    threshold_stats = {}
    for method in CALIBRATION_METHODS:
        for r in results[method]:
            cm = r["cal_metrics"]
            print(
                f"  {method:>8} seed {r['seed']}: threshold={r['cal_threshold']:.4f} "
                f"precision={cm['precision']:.3f} recall={cm['recall']:.3f} f1={cm['f1']:.3f}"
            )
        thresholds = [r["cal_threshold"] for r in results[method]]
        precisions = [r["cal_metrics"]["precision"] for r in results[method]]
        recalls = [r["cal_metrics"]["recall"] for r in results[method]]
        f1s = [r["cal_metrics"]["f1"] for r in results[method]]
        threshold_stats[method] = {
            "threshold_mean": float(np.mean(thresholds)),
            "threshold_std": float(np.std(thresholds)),
            "threshold_range": float(max(thresholds) - min(thresholds)),
            "precision_mean": float(np.mean(precisions)),
            "precision_std": float(np.std(precisions)),
            "recall_mean": float(np.mean(recalls)),
            "recall_std": float(np.std(recalls)),
            "f1_mean": float(np.mean(f1s)),
            "f1_std": float(np.std(f1s)),
        }
        s = threshold_stats[method]
        print(
            f"  {method:>8} threshold stability: mean={s['threshold_mean']:.4f} std={s['threshold_std']:.4f} "
            f"range={s['threshold_range']:.4f}  |  P mean={s['precision_mean']:.3f} std={s['precision_std']:.4f}  "
            f"R mean={s['recall_mean']:.3f} std={s['recall_std']:.4f}  F1 mean={s['f1_mean']:.3f} std={s['f1_std']:.4f}"
        )

    # --- 8: method decision ---
    print("\n" + "=" * 78 + "\n8. METHOD DECISION\n" + "=" * 78)
    sig_gap = np.mean(np.abs(top_bin_stats["sigmoid"]))
    iso_gap = np.mean(np.abs(top_bin_stats["isotonic"]))
    gap_reduction_abs = sig_gap - iso_gap
    gap_reduction_rel = gap_reduction_abs / sig_gap if sig_gap else float("nan")
    materially_smaller = gap_reduction_abs >= 0.03 and gap_reduction_rel >= 0.25

    brier_strong = brier_stats["isotonic"]["improvement_mean"] >= 0.8 * brier_stats["sigmoid"]["improvement_mean"]
    variability_acceptable = (
        threshold_stats["isotonic"]["threshold_std"] <= 3 * threshold_stats["sigmoid"]["threshold_std"] + 1e-9
        and brier_stats["isotonic"]["brier_std"] <= 3 * brier_stats["sigmoid"]["brier_std"] + 1e-9
    )
    operating_point_acceptable = (
        threshold_stats["isotonic"]["precision_std"] <= 3 * threshold_stats["sigmoid"]["precision_std"] + 1e-9
        and threshold_stats["isotonic"]["recall_std"] <= 3 * threshold_stats["sigmoid"]["recall_std"] + 1e-9
    )

    print(f"  top-bin |gap| mean: sigmoid={sig_gap:.4f}  isotonic={iso_gap:.4f}  "
          f"reduction={gap_reduction_abs:+.4f} abs ({gap_reduction_rel:+.1%} rel)")
    print(f"  materially smaller (>=0.03 abs AND >=25% rel reduction)? {materially_smaller}")
    print(f"  Brier improvement remains strong (isotonic >= 80% of sigmoid's)? {brier_strong}  "
          f"(sigmoid={brier_stats['sigmoid']['improvement_mean']:.4f}, isotonic={brier_stats['isotonic']['improvement_mean']:.4f})")
    print(f"  cross-seed variability acceptable (threshold/Brier std <= 3x sigmoid's)? {variability_acceptable}  "
          f"(threshold std: sigmoid={threshold_stats['sigmoid']['threshold_std']:.4f} isotonic={threshold_stats['isotonic']['threshold_std']:.4f}; "
          f"Brier std: sigmoid={brier_stats['sigmoid']['brier_std']:.4f} isotonic={brier_stats['isotonic']['brier_std']:.4f})")
    print(f"  operating-point metrics acceptable (P/R std <= 3x sigmoid's)? {operating_point_acceptable}  "
          f"(precision std: sigmoid={threshold_stats['sigmoid']['precision_std']:.4f} isotonic={threshold_stats['isotonic']['precision_std']:.4f}; "
          f"recall std: sigmoid={threshold_stats['sigmoid']['recall_std']:.4f} isotonic={threshold_stats['isotonic']['recall_std']:.4f})")

    select_isotonic = materially_smaller and brier_strong and variability_acceptable and operating_point_acceptable
    selected_method = "isotonic" if select_isotonic else "sigmoid"
    print(f"\n  RECOMMENDATION: {selected_method.upper()}")

    # --- threshold for the selected method ---
    if selected_method == "sigmoid":
        selected_threshold = SIGMOID_PRODUCTION_THRESHOLD
        print(f"  sigmoid remains selected - confirming previously-recommended threshold {selected_threshold:.4f} (not recomputed).")
        iso_rec = recommend_threshold_for_method(results["isotonic"], y_tr_arr)
        print(
            f"  (isotonic's own mean/median/seed-42 thresholds, reported for completeness, NOT adopted: "
            f"mean={iso_rec['mean_threshold']:.4f} median={iso_rec['median_threshold']:.4f} seed_42={iso_rec['seed_42_threshold']:.4f})"
        )
    else:
        iso_rec = recommend_threshold_for_method(results["isotonic"], y_tr_arr)
        selected_threshold = iso_rec["recommended_threshold"]
        print(f"  isotonic selected - recommended threshold ({iso_rec['recommended_name']}) = {selected_threshold:.4f}")
        print(iso_rec["candidate_summary"].to_string(index=False, float_format=lambda v: f"{v:.4f}"))

    # --- 9/10: sealed test set, selected method only, exactly once ---
    print("\n" + "=" * 78 + "\n9/10. FINAL SEALED TEST-SET CONFIRMATION\n" + "=" * 78)
    test_summary = final_sealed_test_evaluation(X_tr, y_tr, X_te, y_te_arr, plain, selected_method, selected_threshold)
    print(f"  method: {selected_method}  threshold: {selected_threshold:.4f} (fixed before this evaluation)")
    print(f"  test set: {test_summary['n_test']} rows, {test_summary['n_test_positive']} positive")
    print(
        f"  Brier={test_summary['brier_score']:.4f} log_loss={test_summary['log_loss']:.4f} "
        f"ROC-AUC={test_summary['roc_auc']:.4f} mean_predicted={test_summary['mean_predicted_probability']:.4f}"
    )
    print(
        f"  precision={test_summary['precision']:.3f} recall={test_summary['recall']:.3f} "
        f"f1={test_summary['f1']:.3f} confusion_matrix={test_summary['confusion_matrix']}"
    )

    # --- write the one requested artifact ---
    all_results = results["sigmoid"] + results["isotonic"]
    comparison_df = build_comparison_table(all_results)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ARTIFACT_DIR / "calibration_method_comparison.csv"
    comparison_df.to_csv(out_path, index=False)
    print(f"\nsaved {len(comparison_df)} rows to {out_path}")


if __name__ == "__main__":
    main()
