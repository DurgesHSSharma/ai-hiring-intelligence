"""Phase 11 follow-up: persists the owner-approved, frozen empirical
risk-tier cutoffs into decision_threshold.json.

F9.7's Low/Medium/High risk-band decision is resolved by explicit owner
decision (Memory.md, "Current phase and status" / decision entry, this
date): a frozen, ranking-derived three-tier scheme built from the
already-validated four-seed calibrated OOF distribution
(10_risk_tier_percentile_analysis.py / 11_risk_tier_discrimination_analysis.py),
NOT the original PRD F9.7 fixed absolute-probability bands
(<30%/30-60%/>60%), which this supersedes entirely.

This script does not derive anything new - it re-derives the same 4-seed
percentile cutoffs those two analysis scripts already computed and
asserts the result matches the recorded, owner-approved values (mean p90
~= 0.3671, mean p75 ~= 0.2270) before writing anything, exactly the same
drift-guard discipline 09_finalize_calibrated_model.py already established
for the calibrated threshold itself. It does NOT retrain, does NOT touch
calibrated_model.joblib / model.joblib / preprocessor.joblib / metrics.json,
does NOT change the calibrated serving threshold (0.2005) or the raw
evaluation threshold (0.550), and does NOT open the sealed test set.

Writes one new top-level section to decision_threshold.json:
  "risk_tier": {
    scheme, high_cutoff, medium_cutoff, percentile_method,
    oof_seeds, oof_population, derivation_date, source_analysis,
    discrimination_evidence (the 4-seed aggregate this scheme was chosen
    from - Top 10% vs Top 5% vs Top 2%, per Memory.md's owner-decision
    entry), known_limitation
  }
The existing "threshold" (0.550) and "calibrated" (0.2005) sections are
left byte-for-byte untouched.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
from sklearn.model_selection import train_test_split

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"

# Owner-approved scheme (Memory.md, this date) - asserted against, not
# reinvented. Percentiles are computed per seed, then averaged, exactly as
# 10_risk_tier_percentile_analysis.py's report already did.
HIGH_PERCENTILE = 90
MEDIUM_PERCENTILE = 75
_EXPECTED_HIGH_CUTOFF = 0.3671
_EXPECTED_MEDIUM_CUTOFF = 0.2270
_CUTOFF_TOLERANCE = 0.0005

DERIVATION_DATE = "2026-08-30"
SOURCE_ANALYSIS = [
    "ml/attrition/10_risk_tier_percentile_analysis.py",
    "ml/attrition/11_risk_tier_discrimination_analysis.py",
]

_MULTISEED_PATH = Path(__file__).resolve().parent / "07_calibration_multiseed.py"
_spec = importlib.util.spec_from_file_location("attrition_calibration_multiseed", _MULTISEED_PATH)
_multiseed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_multiseed)

_train = _multiseed._train
RANDOM_STATE = _multiseed.RANDOM_STATE
TEST_SIZE = _multiseed.TEST_SIZE
CALIBRATION_SEEDS = _multiseed.CALIBRATION_SEEDS
run_one_seed = _multiseed.run_one_seed

# Same drift guard 09/10/11 already use, so this script also refuses to run
# against a calibration pipeline that has silently drifted from decision 70.
_EXPECTED_SEED42_BRIER_CAL = 0.1062
_EXPECTED_SEED42_THRESHOLD = 0.1971
_SEED42_TOLERANCE = 0.0005


def main() -> None:
    print("=" * 78)
    print("Phase 11: finalizing owner-approved frozen empirical risk-tier cutoffs.")
    print("=" * 78)

    X, y = _train.load_and_clean(_train.DATA_PATH)
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=TEST_SIZE, stratify=y, random_state=RANDOM_STATE)
    del X_te, y_te  # sealed test set: split off, never used below
    y_tr_arr = np.asarray(y_tr)
    prevalence = float(y_tr_arr.mean())
    print(f"\ntrain/OOF pool: {len(X_tr)} rows, {int(y_tr_arr.sum())} positive")

    plain = _train.build_plain_estimators()
    results = [run_one_seed(seed, X_tr, y_tr, y_tr_arr, plain, prevalence) for seed in CALIBRATION_SEEDS]

    seed42 = next(r for r in results if r["seed"] == 42)
    if (
        abs(seed42["brier_cal"] - _EXPECTED_SEED42_BRIER_CAL) > _SEED42_TOLERANCE
        or abs(seed42["cal_threshold"] - _EXPECTED_SEED42_THRESHOLD) > _SEED42_TOLERANCE
    ):
        raise RuntimeError(
            "Recomputed seed-42 calibration numbers do not match Memory.md decision 70's "
            "recorded values. Stopping rather than finalizing risk-tier cutoffs on numbers "
            "that don't match the trusted baseline."
        )
    print("Drift guard 1/2 passed: recomputed seed-42 calibration matches decision 70.")

    high_cutoffs = [float(np.percentile(r["oof_cal"], HIGH_PERCENTILE)) for r in results]
    medium_cutoffs = [float(np.percentile(r["oof_cal"], MEDIUM_PERCENTILE)) for r in results]
    mean_high = round(float(np.mean(high_cutoffs)), 4)
    mean_medium = round(float(np.mean(medium_cutoffs)), 4)
    print(f"\nper-seed p{HIGH_PERCENTILE} (High) cutoffs: {dict(zip(CALIBRATION_SEEDS, high_cutoffs))}")
    print(f"per-seed p{MEDIUM_PERCENTILE} (Medium) cutoffs: {dict(zip(CALIBRATION_SEEDS, medium_cutoffs))}")
    print(f"mean High cutoff:   {mean_high}")
    print(f"mean Medium cutoff: {mean_medium}")

    if abs(mean_high - _EXPECTED_HIGH_CUTOFF) > _CUTOFF_TOLERANCE or abs(mean_medium - _EXPECTED_MEDIUM_CUTOFF) > _CUTOFF_TOLERANCE:
        raise RuntimeError(
            "Recomputed mean risk-tier cutoffs do not match the owner-approved recorded "
            f"values (expected High~={_EXPECTED_HIGH_CUTOFF}, Medium~={_EXPECTED_MEDIUM_CUTOFF}; "
            f"got High={mean_high}, Medium={mean_medium}). Stopping rather than persisting "
            "cutoffs that don't match what was actually approved."
        )
    print("Drift guard 2/2 passed: recomputed mean cutoffs match the owner-approved values.")

    threshold_path = ARTIFACT_DIR / "decision_threshold.json"
    with open(threshold_path, encoding="utf-8") as f:
        threshold_doc = json.load(f)

    threshold_doc["risk_tier"] = {
        "scheme": "top10_high_next15_medium",
        "high_cutoff": mean_high,
        "medium_cutoff": mean_medium,
        "percentile_method": (
            f"Per-seed p{HIGH_PERCENTILE} (High) / p{MEDIUM_PERCENTILE} (Medium) computed "
            "independently on each seed's own calibrated out-of-fold probability array "
            "(np.percentile), then averaged across seeds. Not a live percentile - frozen "
            "at derivation time from the validated training/OOF pool, never recomputed "
            "against the current employees table or a request's own population."
        ),
        "oof_seeds": CALIBRATION_SEEDS,
        "oof_population": int(len(seed42["oof_cal"])),
        "derivation_date": DERIVATION_DATE,
        "source_analysis": SOURCE_ANALYSIS,
        "discrimination_evidence_4_seed": {
            "top10_high_next15_medium": {
                "high_pct_of_population": 10.03,
                "high_attrition_rate_mean": 0.6271,
                "high_attrition_rate_std": 0.0120,
                "high_leaver_capture_pct_mean": 38.95,
                "high_leaver_capture_pct_std": 0.74,
                "high_minus_low_separation_mean": 0.5520,
                "high_minus_low_separation_std": 0.0127,
                "monotonic_all_4_seeds": True,
            },
            "top5_high_next15_medium": {
                "high_pct_of_population": 5.02,
                "high_attrition_rate_mean": 0.6992,
                "high_attrition_rate_std": 0.0349,
                "high_leaver_capture_pct_mean": 21.71,
                "high_leaver_capture_pct_std": 1.08,
                "high_minus_low_separation_mean": 0.6132,
                "high_minus_low_separation_std": 0.0363,
                "monotonic_all_4_seeds": True,
            },
            "top2_high_next14_medium": {
                "high_pct_of_population": 2.04,
                "high_attrition_rate_mean": 0.7812,
                "high_attrition_rate_std": 0.0208,
                "high_leaver_capture_pct_mean": 9.87,
                "high_leaver_capture_pct_std": 0.27,
                "high_minus_low_separation_mean": 0.6875,
                "high_minus_low_separation_std": 0.0206,
                "monotonic_all_4_seeds": True,
            },
        },
        "why_top10_selected": (
            "Top 10% captures ~39% of actual OOF leavers versus ~22% for Top 5% and ~10% "
            "for Top 2%, while still separating High from Low by ~55 percentage points of "
            "observed attrition rate. Top 2% is the most concentrated but misses ~90% of "
            "actual leavers; Top 10% is the only candidate of the three that captures a "
            "clearly substantial share of leavers rather than a small minority. Owner "
            "decision, evidence-supported (Memory.md, this date) - not a default or a "
            "visual preference."
        ),
        "known_limitation": (
            "The sigmoid calibration's highest decile under-predicts actual risk by "
            "roughly 12-15 percentage points (Memory.md decision 70, confirmed across "
            "all 4 seeds) - the ranking/ordering evidence behind this tier scheme is "
            "solid (monotonic and stable across seeds), but the displayed probability "
            "for employees deep in the High tier should be read as a conservative floor "
            "on real risk, not an exact figure. This is a calibration-tail limitation, "
            "not a defect in the tier boundaries themselves."
        ),
        "not_a_generalization_claim": (
            "These cutoffs are frozen from the validated 1,176-row training/OOF "
            "population and are intended as a stable production display scheme. This "
            "does not claim that a future employee population will show exactly these "
            "same tier percentages or leaver-capture rates - it is a fixed rule applied "
            "consistently, not a live re-ranking against whichever population exists at "
            "prediction time."
        ),
    }

    with open(threshold_path, "w", encoding="utf-8") as f:
        json.dump(threshold_doc, f, indent=2)

    print(f"\nsaved risk_tier section to {threshold_path}")
    print("Existing top-level 'threshold' (0.550) and 'calibrated' (0.2005) sections untouched.")


if __name__ == "__main__":
    main()
