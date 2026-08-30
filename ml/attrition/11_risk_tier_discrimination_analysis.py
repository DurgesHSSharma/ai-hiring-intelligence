"""Phase 11 follow-up: does each candidate ranking-derived risk-tier scheme
actually discriminate attrition risk? - ANALYSIS ONLY, not production.

10_risk_tier_percentile_analysis.py derived stable percentile cutoffs from
the calibrated OOF distribution but never checked them against the actual
outcome label - a stable cutoff says nothing about whether the resulting
tiers separate real leavers from real stayers. This script closes that gap
for the three illustrative schemes that script's report surfaced, using
OOF data ONLY: X_te/y_te (the sealed test set) are split off exactly once,
by the same train_test_split call every other Phase 10/11 script uses, and
then never referenced again below that line - no sealed-test metric of any
kind is computed in this file.

Does NOT change 03_train.py's SELECTED_MODEL/SELECTED_STRATEGY/
DECISION_THRESHOLD, does NOT touch calibrated_model.joblib, 0.2005,
decision_threshold.json, risk_level, RISK_BAND_RESOLVED, or any serving
code. Selects no scheme - reports discrimination evidence for all three so
the project owner can decide with numbers in hand, per explicit
instruction not to pick one here.

Method, reusing existing validated code with zero duplication (same
importlib precedent 07/08/09/10 already established):
  - `07_calibration_multiseed.py`'s run_one_seed() is called exactly as
    09_finalize_calibrated_model.py and 10_risk_tier_percentile_analysis.py
    already call it, returning `oof_cal` (the per-row calibrated OOF
    probability array) and using the shared `y_tr_arr` (actual attrition
    labels for those same 1,176 rows) already computed once from the
    identical, unchanged 80/20 split.
  - Before computing anything new, this script asserts the recomputed
    seed-42 Brier/threshold numbers match Memory.md decision 70's recorded
    values (the same drift guard 09 and 10 both use) - stops rather than
    building tier-discrimination evidence on numbers that don't match the
    trusted baseline.
  - For each of the three candidate schemes and each seed, tier cutoffs
    are computed from THAT SEED's own oof_cal distribution (np.percentile,
    matching 10_risk_tier_percentile_analysis.py's per-seed convention,
    since fold assignment differs by seed and so does the resulting OOF
    score array, even though the underlying 1,176 rows and their labels
    never change). Each row is assigned to Low/Medium/High by comparing
    its own calibrated OOF score against that seed's cutoffs, then
    attrition rate, leaver counts, and leaver-capture percentages are
    computed directly against y_tr_arr - the real outcome, not a proxy.

No scheme is selected, no cutoff is frozen, and nothing beyond one
descriptive CSV artifact is written.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"

# The three candidate schemes surfaced by 10_risk_tier_percentile_analysis.py's
# report - not a recommendation, just what is being evaluated here.
CANDIDATE_SCHEMES = {
    "top10_high_next15_medium": (90, 75),
    "top5_high_next15_medium": (95, 80),
    "top2_high_next14_medium": (98, 84),
}

# Decision 70's recorded seed-42 values - same drift guard as
# 09_finalize_calibrated_model.py / 10_risk_tier_percentile_analysis.py.
_EXPECTED_SEED42_BRIER_CAL = 0.1062
_EXPECTED_SEED42_THRESHOLD = 0.1971
_TOLERANCE = 0.0005

_MULTISEED_PATH = Path(__file__).resolve().parent / "07_calibration_multiseed.py"
_spec = importlib.util.spec_from_file_location("attrition_calibration_multiseed", _MULTISEED_PATH)
_multiseed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_multiseed)

_train = _multiseed._train
RANDOM_STATE = _multiseed.RANDOM_STATE
TEST_SIZE = _multiseed.TEST_SIZE
CALIBRATION_SEEDS = _multiseed.CALIBRATION_SEEDS
run_one_seed = _multiseed.run_one_seed


def tier_discrimination(oof_cal: np.ndarray, y_arr: np.ndarray, high_q: float, medium_q: float) -> dict:
    """Assigns each row to Low/Medium/High by this seed's own percentile
    cutoffs, then measures discrimination against the real label y_arr.
    Never touches the sealed test set - y_arr here is always y_tr_arr."""
    high_cut = float(np.percentile(oof_cal, high_q))
    medium_cut = float(np.percentile(oof_cal, medium_q))

    is_high = oof_cal >= high_cut
    is_medium = (oof_cal >= medium_cut) & ~is_high
    is_low = ~is_high & ~is_medium

    total_leavers = int(y_arr.sum())
    out = {"high_cutoff": high_cut, "medium_cutoff": medium_cut, "total_leavers": total_leavers}
    for label, mask in [("low", is_low), ("medium", is_medium), ("high", is_high)]:
        n = int(mask.sum())
        leavers = int(y_arr[mask].sum())
        rate = leavers / n if n else float("nan")
        out[f"n_{label}"] = n
        out[f"attrition_rate_{label}"] = rate
        out[f"leavers_{label}"] = leavers
        out[f"pct_of_oof_population_{label}"] = round(100 * n / len(y_arr), 2)
        out[f"share_of_all_leavers_{label}"] = round(100 * leavers / total_leavers, 2) if total_leavers else float("nan")
    out["pct_leavers_captured_by_high"] = out["share_of_all_leavers_high"]
    out["pct_leavers_captured_by_high_plus_medium"] = round(
        100 * (out["leavers_high"] + out["leavers_medium"]) / total_leavers, 2
    )
    out["separation_high_minus_low"] = out["attrition_rate_high"] - out["attrition_rate_low"]
    out["monotonic"] = out["attrition_rate_high"] > out["attrition_rate_medium"] > out["attrition_rate_low"]
    return out


def main() -> None:
    print("=" * 78)
    print("Phase 11 follow-up: risk-tier discrimination analysis (OOF only) - ANALYSIS ONLY.")
    print("=" * 78)

    X, y = _train.load_and_clean(_train.DATA_PATH)
    # X_te/y_te split off here exactly once, matching every other Phase 10/11
    # script's convention - and never referenced again below this line.
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=TEST_SIZE, stratify=y, random_state=RANDOM_STATE)
    del X_te, y_te  # explicit: the sealed test set is not used anywhere in this file
    y_tr_arr = np.asarray(y_tr)
    prevalence = float(y_tr_arr.mean())
    print(f"\ntrain/OOF pool: {len(X_tr)} rows, {int(y_tr_arr.sum())} positive (prevalence={prevalence:.4f})")
    print("Sealed test set: split off, then discarded (del) - not used anywhere below.")

    plain = _train.build_plain_estimators()
    results = [run_one_seed(seed, X_tr, y_tr, y_tr_arr, plain, prevalence) for seed in CALIBRATION_SEEDS]

    seed42 = next(r for r in results if r["seed"] == 42)
    if (
        abs(seed42["brier_cal"] - _EXPECTED_SEED42_BRIER_CAL) > _TOLERANCE
        or abs(seed42["cal_threshold"] - _EXPECTED_SEED42_THRESHOLD) > _TOLERANCE
    ):
        raise RuntimeError(
            "Recomputed seed-42 calibration numbers do not match Memory.md decision 70's "
            f"recorded values (expected brier~={_EXPECTED_SEED42_BRIER_CAL}, "
            f"threshold~={_EXPECTED_SEED42_THRESHOLD}; got brier={seed42['brier_cal']:.4f}, "
            f"threshold={seed42['cal_threshold']:.4f}). Stopping rather than building "
            "discrimination evidence on numbers that don't match the trusted baseline."
        )
    print("\nDrift guard passed: recomputed seed-42 numbers match Memory.md decision 70.")

    all_rows = []
    for scheme_name, (high_q, medium_q) in CANDIDATE_SCHEMES.items():
        print("\n" + "=" * 78)
        print(f"SCHEME: {scheme_name}  (High >= p{high_q}, Medium >= p{medium_q})")
        print("=" * 78)
        scheme_seed_rows = []
        for r in results:
            d = tier_discrimination(r["oof_cal"], y_tr_arr, high_q, medium_q)
            d["scheme"] = scheme_name
            d["seed"] = r["seed"]
            scheme_seed_rows.append(d)
            all_rows.append(d)
            print(f"\n  seed {r['seed']}:")
            print(
                f"    Low:    n={d['n_low']:>4} ({d['pct_of_oof_population_low']:>5.2f}%)  "
                f"attrition_rate={d['attrition_rate_low']:.4f}  leavers={d['leavers_low']:>3}  "
                f"share_of_leavers={d['share_of_all_leavers_low']:>5.2f}%"
            )
            print(
                f"    Medium: n={d['n_medium']:>4} ({d['pct_of_oof_population_medium']:>5.2f}%)  "
                f"attrition_rate={d['attrition_rate_medium']:.4f}  leavers={d['leavers_medium']:>3}  "
                f"share_of_leavers={d['share_of_all_leavers_medium']:>5.2f}%"
            )
            print(
                f"    High:   n={d['n_high']:>4} ({d['pct_of_oof_population_high']:>5.2f}%)  "
                f"attrition_rate={d['attrition_rate_high']:.4f}  leavers={d['leavers_high']:>3}  "
                f"share_of_leavers={d['share_of_all_leavers_high']:>5.2f}%"
            )
            print(
                f"    High captures {d['pct_leavers_captured_by_high']:.2f}% of {d['total_leavers']} OOF leavers; "
                f"High+Medium captures {d['pct_leavers_captured_by_high_plus_medium']:.2f}%"
            )
            print(f"    separation (High - Low attrition rate): {d['separation_high_minus_low']:+.4f}")
            print(f"    monotonic (High > Medium > Low): {d['monotonic']}")

        # per-scheme cross-seed aggregate
        df = pd.DataFrame(scheme_seed_rows)
        print(f"\n  --- {scheme_name}: cross-seed aggregate (mean +/- std) ---")
        for col in [
            "pct_of_oof_population_high",
            "attrition_rate_high",
            "attrition_rate_medium",
            "attrition_rate_low",
            "pct_leavers_captured_by_high",
            "pct_leavers_captured_by_high_plus_medium",
            "separation_high_minus_low",
        ]:
            print(f"    {col}: mean={df[col].mean():.4f}  std={df[col].std():.4f}")
        all_monotonic = bool(df["monotonic"].all())
        print(f"    monotonic in ALL 4 seeds: {all_monotonic}")
        if not all_monotonic:
            failing = df.loc[~df["monotonic"], "seed"].tolist()
            print(f"    *** MONOTONICITY FAILURE in seed(s): {failing} ***")

    result_df = pd.DataFrame(all_rows)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ARTIFACT_DIR / "risk_tier_discrimination_analysis.csv"
    result_df.to_csv(out_path, index=False)
    print(f"\nsaved {len(result_df)} rows to {out_path}")


if __name__ == "__main__":
    main()
