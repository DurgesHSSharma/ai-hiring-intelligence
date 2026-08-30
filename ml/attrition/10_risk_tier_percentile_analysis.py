"""Phase 11 follow-up: empirical, ranking-derived risk-tier cutoffs from the
already-validated calibrated OOF score distribution - ANALYSIS ONLY, not
production. Does NOT change 03_train.py's SELECTED_MODEL/SELECTED_STRATEGY/
DECISION_THRESHOLD, does NOT change calibrated_model.joblib or the 0.2005
serving threshold, does NOT touch predictor.py/attrition_service.py/
schemas/attrition.py, and does NOT flip RISK_BAND_RESOLVED. Saves one new,
purely analytical artifact (risk_tier_percentile_analysis.csv) - the same
"ANALYSIS ONLY" convention 06/07/08_calibration_*.py already established
for this project, none of which are wired into serving on their own.

Why this exists: PRD F9.7's original design fixes absolute probability
bands (<30%/30-60%/>60%) - Memory.md decisions 69/70 already measured that
those bands are the wrong shape for this model's calibrated output (the
High band is thin, ~2%, and likely an undercount given the top-decile
under-prediction). An alternative under evaluation is a RANKING-derived
tier instead: pick a tier by where a probability falls in the observed
OOF distribution (e.g. "top 10% of employees by calibrated risk"), not by
a fixed absolute probability meaning. This script derives what that would
actually look like from real evidence - it does not decide which
percentile split to adopt, and does not decide whether to adopt this
design over F9.7's fixed bands at all. Both are project-owner decisions.

Method, reusing existing validated code with zero duplication (same
`importlib` precedent 07/08/09 already established for this
digit-prefixed-filename directory):
  - `07_calibration_multiseed.py`'s run_one_seed() is called exactly as
    09_finalize_calibrated_model.py already calls it, and returns
    (among other things) `oof_cal` - the raw, per-row, 1,176-length array
    of calibrated out-of-fold probabilities for that seed. This is the
    real population a "ranking within the training/OOF pool" percentile
    is computed against; nothing here re-fits anything.
  - Before computing anything new, this script asserts the recomputed
    seed-42 Brier/threshold numbers match Memory.md decision 70's recorded
    values (the same drift guard 09_finalize_calibrated_model.py uses) -
    if the recompute doesn't match, something upstream has silently
    drifted and this script stops rather than deriving tier cutoffs from
    numbers nobody can trust.
  - For a range of illustrative percentile points (50/75/80/85/90/95/98/99
    - NOT a decided tier scheme, just enough resolution to let a person
    choose one), computes np.percentile(oof_cal, q) independently per
    seed, then reports the cross-seed mean/std/range for each percentile
    point - the stability check this design explicitly requires before
    any cutoff is frozen (see the report this script's stdout feeds).
  - Also reports, for three illustrative 3-tier candidate schemes (not a
    recommendation), the resulting Low/Medium/High counts and percentages
    within each seed's 1,176-row OOF pool, so a person can see what an
    actual percentile split would produce before choosing one.

This script picks no tier scheme and freezes nothing. Persisting a chosen
set of cutoffs into decision_threshold.json (or a new artifact) and wiring
them into serving code is explicitly deferred to a follow-up step, once
the exact percentile split per tier is confirmed - inventing that split
here would be exactly the kind of guessed number this design is meant to
avoid.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
ILLUSTRATIVE_PERCENTILES = [50, 75, 80, 85, 90, 95, 98, 99]

# Decision 70's recorded seed-42 values - the drift guard below asserts
# against these before any new number is derived.
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


def illustrative_tier_scheme(oof_cal: np.ndarray, high_q: float, medium_q: float) -> dict:
    """Given two percentile cutoffs (medium_q < high_q, e.g. 75 and 90),
    reports the resulting 3-tier counts/pct within this seed's OOF pool.
    Purely descriptive - not a recommendation of which split to use."""
    high_cut = float(np.percentile(oof_cal, high_q))
    medium_cut = float(np.percentile(oof_cal, medium_q))
    n = len(oof_cal)
    n_high = int((oof_cal >= high_cut).sum())
    n_medium = int(((oof_cal >= medium_cut) & (oof_cal < high_cut)).sum())
    n_low = n - n_high - n_medium
    return {
        "high_percentile": high_q,
        "medium_percentile": medium_q,
        "high_cutoff": high_cut,
        "medium_cutoff": medium_cut,
        "n_total": n,
        "n_low": n_low,
        "pct_low": round(100 * n_low / n, 2),
        "n_medium": n_medium,
        "pct_medium": round(100 * n_medium / n, 2),
        "n_high": n_high,
        "pct_high": round(100 * n_high / n, 2),
    }


def main() -> None:
    print("=" * 78)
    print("Phase 11 follow-up: ranking-derived risk-tier percentile analysis - ANALYSIS ONLY.")
    print("=" * 78)

    X, y = _train.load_and_clean(_train.DATA_PATH)
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=TEST_SIZE, stratify=y, random_state=RANDOM_STATE)
    y_tr_arr = np.asarray(y_tr)
    prevalence = float(y_tr_arr.mean())
    print(f"\ntrain/OOF pool: {len(X_tr)} rows, {int(y_tr_arr.sum())} positive (prevalence={prevalence:.4f})")

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
            f"threshold={seed42['cal_threshold']:.4f}). Stopping rather than deriving new "
            "tier cutoffs from numbers that don't match the trusted baseline."
        )
    print("\nDrift guard passed: recomputed seed-42 numbers match Memory.md decision 70.")

    # --- A: percentile cutoffs per seed, at each illustrative percentile ---
    print("\n" + "=" * 78 + "\nA. PERCENTILE CUTOFFS PER SEED (calibrated OOF probability)\n" + "=" * 78)
    cutoff_rows = []
    for r in results:
        oof_cal = r["oof_cal"]
        for q in ILLUSTRATIVE_PERCENTILES:
            cutoff = float(np.percentile(oof_cal, q))
            cutoff_rows.append({"seed": r["seed"], "percentile": q, "cutoff": cutoff, "n_oof": len(oof_cal)})
    cutoff_df = pd.DataFrame(cutoff_rows)
    pivot = cutoff_df.pivot(index="percentile", columns="seed", values="cutoff")
    print(pivot.to_string(float_format=lambda v: f"{v:.4f}"))

    # --- B: cross-seed stability per percentile point ---
    print("\n" + "=" * 78 + "\nB. CROSS-SEED STABILITY PER PERCENTILE POINT\n" + "=" * 78)
    stability_rows = []
    for q in ILLUSTRATIVE_PERCENTILES:
        vals = cutoff_df.loc[cutoff_df["percentile"] == q, "cutoff"].values
        mean_v, std_v = float(np.mean(vals)), float(np.std(vals))
        rel_std = std_v / mean_v if mean_v else float("nan")
        stability_rows.append(
            {
                "percentile": q,
                "mean_cutoff": mean_v,
                "std_cutoff": std_v,
                "relative_std_pct": round(100 * rel_std, 2),
                "min_cutoff": float(np.min(vals)),
                "max_cutoff": float(np.max(vals)),
                "range": float(np.max(vals) - np.min(vals)),
            }
        )
        print(
            f"  p{q:>2}: mean={mean_v:.4f}  std={std_v:.4f} ({100*rel_std:.1f}% relative)  "
            f"range=[{np.min(vals):.4f}, {np.max(vals):.4f}]"
        )
    stability_df = pd.DataFrame(stability_rows)

    # --- C: illustrative 3-tier schemes (NOT a recommendation) ---
    print("\n" + "=" * 78 + "\nC. ILLUSTRATIVE 3-TIER SCHEMES (descriptive only, no scheme is selected here)\n" + "=" * 78)
    schemes = {
        "top-10%-High / next-15%-Medium": (90, 75),
        "top-5%-High / next-15%-Medium": (95, 80),
        "top-2%-High / next-14%-Medium (mirrors F9.7's observed sigmoid proportions)": (98, 84),
    }
    scheme_rows = []
    for label, (high_q, medium_q) in schemes.items():
        print(f"\n  scheme: {label}")
        for r in results:
            s = illustrative_tier_scheme(r["oof_cal"], high_q, medium_q)
            s["scheme"] = label
            s["seed"] = r["seed"]
            scheme_rows.append(s)
            print(
                f"    seed {r['seed']}: High cutoff>={s['high_cutoff']:.4f} (n={s['n_high']}, {s['pct_high']}%)  "
                f"Medium cutoff>={s['medium_cutoff']:.4f} (n={s['n_medium']}, {s['pct_medium']}%)  "
                f"Low (n={s['n_low']}, {s['pct_low']}%)"
            )
    scheme_df = pd.DataFrame(scheme_rows)

    # --- write the one analytical artifact ---
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    cutoff_out = ARTIFACT_DIR / "risk_tier_percentile_analysis.csv"
    merged = cutoff_df.merge(
        stability_df[["percentile", "mean_cutoff", "std_cutoff", "relative_std_pct"]], on="percentile", how="left"
    )
    merged.to_csv(cutoff_out, index=False)
    scheme_out = ARTIFACT_DIR / "risk_tier_scheme_illustrations.csv"
    scheme_df.to_csv(scheme_out, index=False)
    print(f"\nsaved {len(merged)} rows to {cutoff_out}")
    print(f"saved {len(scheme_df)} rows to {scheme_out}")

    print("\n--- JSON echo (report use only) ---")
    print(
        json.dumps(
            {
                "seeds": CALIBRATION_SEEDS,
                "oof_pool_size": len(seed42["oof_cal"]),
                "drift_guard_passed": True,
                "percentile_cutoff_stability": stability_rows,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
