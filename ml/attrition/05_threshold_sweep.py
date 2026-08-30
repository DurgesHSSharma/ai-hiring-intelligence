"""Phase 10 follow-up, round 2.

Fixes a real methodology gap the project owner caught in the round-1 sweep:
the preprocessor was fit once on the whole training fold *before*
cross-validation, so every fold's validation rows influenced the
imputation/scaling statistics applied to themselves - the same class of
leakage SMOTE's fold-safety was already protecting against, just for a
different transform. Preprocessing now lives inside the same
imblearn.pipeline.Pipeline as SMOTE and the classifier, so
cross_val_predict refits imputation/scaling/encoding, resampling, and the
model on each fold's training rows only.

ml/attrition/artifacts/threshold_sweep.csv (2,352 rows, single seed 42,
preprocessor fit once outside CV) is round 1's output, produced before this
fix. It is frozen and is never written by this script - see decision 68.
This script writes two new artifacts instead:
  - threshold_sweep_multiseed.csv: the same LogReg+SMOTE vs. XGBoost+SMOTE
    comparison repeated across 4 independent StratifiedKFold seeds
    (42-45), to check round 1's finding is not an artifact of one
    particular fold assignment.
  - calibration_comparison.csv: a separate analysis of whether
    Logistic Regression + SMOTE's raw output probabilities can be read as
    literal attrition probabilities, compared against
    Logistic Regression + class_weight="balanced".

Never touches the test set anywhere in this file. Only the outer 80/20
split's random_state (42) and the classifiers' own random_state (42,
matching 03_train.py throughout) stay fixed across seeds; only the
StratifiedKFold seed varies, exactly as requested - SMOTE's own
random_state stays at 42 in every run so that changing the fold
assignment is the only thing being tested.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
from imblearn.over_sampling import SMOTE
from imblearn.pipeline import Pipeline as ImbPipeline
from sklearn.metrics import brier_score_loss, precision_recall_curve
from sklearn.model_selection import StratifiedKFold, cross_val_predict, train_test_split

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
RECALL_TARGETS = [0.60, 0.70, 0.80]
SWEEP_SEEDS = [42, 43, 44, 45]
TIE_TOLERANCE = 0.01  # abs precision diff below this counts as a tie, not a win

# 03_train.py's filename starts with a digit and can't be `import`ed
# normally (same constraint 02_preprocessing.py documents). Loading it
# reuses its exact estimator definitions and split constants so this sweep
# cannot silently drift from what 03_train.py actually compared.
_TRAIN_PATH = Path(__file__).resolve().parent / "03_train.py"
_spec = importlib.util.spec_from_file_location("attrition_train", _TRAIN_PATH)
_train = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_train)

RANDOM_STATE = _train.RANDOM_STATE
TEST_SIZE = _train.TEST_SIZE
N_SPLITS = _train.N_SPLITS


def _preprocessor_transformer() -> object:
    """The bare ColumnTransformer, not 02_preprocessing's Pipeline wrapper around it.

    sklearn/imblearn refuse a Pipeline nested as an intermediate step of
    another Pipeline ("All intermediate steps ... should not be
    Pipelines") - the ColumnTransformer itself is a fine intermediate
    step, so it's unwrapped here rather than duplicating its definition.
    """
    return _train.build_pipeline().named_steps["preprocess"]


def build_smote_pipeline(model_key: str, plain: dict) -> ImbPipeline:
    """Preprocessing + SMOTE + classifier as ONE pipeline.

    Passed unfitted into cross_val_predict, which clones (and therefore
    re-creates, still unfitted) this entire structure per fold - so
    imputation/scaling/encoding and SMOTE resampling both refit on that
    fold's training rows only. No step here is ever fit on data outside
    the fold it is cloned into.
    """
    return ImbPipeline(
        [
            ("preprocess", _preprocessor_transformer()),
            ("smote", SMOTE(random_state=RANDOM_STATE)),
            ("clf", plain[model_key]),
        ]
    )


def build_balanced_pipeline(model_key: str, balanced: dict) -> ImbPipeline:
    """Preprocessing + class-weighted classifier, no resampling step."""
    return ImbPipeline([("preprocess", _preprocessor_transformer()), ("clf", balanced[model_key])])


def sweep_one(
    name: str, seed: int, pipeline: ImbPipeline, X: pd.DataFrame, y: pd.Series, cv: StratifiedKFold
) -> pd.DataFrame:
    """Out-of-fold predict_proba -> the full precision/recall/F1 curve for one model/seed."""
    oof_proba = cross_val_predict(pipeline, X, y, cv=cv, method="predict_proba")[:, 1]
    precision, recall, thresholds = precision_recall_curve(y, oof_proba)
    # precision_recall_curve appends one extra (precision=1, recall=0)
    # sentinel point with no corresponding threshold - drop it so every
    # remaining row has a real, usable threshold.
    precision, recall = precision[:-1], recall[:-1]
    denom = precision + recall
    f1 = np.where(denom > 0, 2 * precision * recall / np.where(denom > 0, denom, 1), 0.0)
    return pd.DataFrame(
        {
            "seed": seed,
            "model": name,
            "threshold": thresholds,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    )


def best_precision_at_recall(df: pd.DataFrame, min_recall: float) -> tuple[float, float, float] | None:
    """(threshold, precision, recall) of the highest-precision row with recall >= min_recall."""
    candidates = df[df["recall"] >= min_recall]
    if candidates.empty:
        return None
    row = candidates.loc[candidates["precision"].idxmax()]
    return float(row["threshold"]), float(row["precision"]), float(row["recall"])


def run_multiseed_sweep(X_tr: pd.DataFrame, y_tr: pd.Series, plain: dict) -> pd.DataFrame:
    frames = []
    for seed in SWEEP_SEEDS:
        cv = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=seed)
        for name, model_key in [("logreg_smote", "logreg"), ("xgboost_smote", "xgboost")]:
            pipeline = build_smote_pipeline(model_key, plain)
            frames.append(sweep_one(name, seed, pipeline, X_tr, y_tr, cv))
    return pd.concat(frames, ignore_index=True)


def recall_target_table(sweep_df: pd.DataFrame) -> pd.DataFrame:
    """Per (seed, model, recall_target): best precision achievable and at what threshold."""
    rows = []
    for seed in SWEEP_SEEDS:
        for name in ["logreg_smote", "xgboost_smote"]:
            df = sweep_df[(sweep_df["seed"] == seed) & (sweep_df["model"] == name)]
            for target in RECALL_TARGETS:
                result = best_precision_at_recall(df, target)
                threshold, precision, recall = result if result is not None else (float("nan"),) * 3
                rows.append(
                    {
                        "seed": seed,
                        "model": name,
                        "recall_target": target,
                        "threshold": threshold,
                        "precision": precision,
                        "recall": recall,
                    }
                )
    return pd.DataFrame(rows)


def tally_wins(target_df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """The 4-seed x 3-target = 12 head-to-head comparisons, plus the win/tie tally."""
    pivot = target_df.pivot(index=["seed", "recall_target"], columns="model", values="precision")
    pivot["diff_logreg_minus_xgboost"] = pivot["logreg_smote"] - pivot["xgboost_smote"]
    logreg_wins = int((pivot["diff_logreg_minus_xgboost"] > TIE_TOLERANCE).sum())
    xgboost_wins = int((pivot["diff_logreg_minus_xgboost"] < -TIE_TOLERANCE).sum())
    ties = int(pivot["diff_logreg_minus_xgboost"].abs().le(TIE_TOLERANCE).sum())
    return pivot.reset_index(), {"logreg_wins": logreg_wins, "xgboost_wins": xgboost_wins, "ties": ties}


def calibration_comparison(X_tr: pd.DataFrame, y_tr: pd.Series, plain: dict, balanced: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Logistic Regression + class_weight='balanced' vs. + SMOTE: is either one's raw
    probability a usable estimate of real-world attrition probability?

    Single seed (42), same fold structure as everywhere else in Phase 10 -
    this is a separate question from the multi-seed model/threshold
    decision above, not a robustness check of it. Bins are built directly
    with pd.qcut (not sklearn's calibration_curve, which reports
    fraction-positive per bin but not how many observations - or how many
    positives - back it) so a bin-level SMOTE-vs-balanced comparison can be
    told apart from a difference of a handful of positives on a small base.
    """
    cv = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)
    configs = {
        "logreg_balanced": build_balanced_pipeline("logreg", balanced),
        "logreg_smote": build_smote_pipeline("logreg", plain),
    }
    prevalence = float(y_tr.mean())
    y_arr = np.asarray(y_tr)

    bin_rows = []
    summary_rows = []
    for name, pipeline in configs.items():
        oof_proba = cross_val_predict(pipeline, X_tr, y_tr, cv=cv, method="predict_proba")[:, 1]
        brier = float(brier_score_loss(y_tr, oof_proba))
        mean_pred = float(oof_proba.mean())
        ratio = mean_pred / prevalence

        bin_labels = pd.qcut(oof_proba, q=10, duplicates="drop")
        grouped = (
            pd.DataFrame({"proba": oof_proba, "y": y_arr, "bin": bin_labels})
            .groupby("bin", observed=True)
            .agg(
                n=("y", "size"),
                n_positive=("y", "sum"),
                mean_predicted=("proba", "mean"),
                fraction_positive=("y", "mean"),
            )
            .reset_index(drop=True)
        )

        print(
            f"\n{name} [training-fold OOF, seed=42]: Brier score={brier:.4f}, "
            f"mean predicted P(positive)={mean_pred:.4f}, actual prevalence={prevalence:.4f}, "
            f"ratio={ratio:.2f}x"
        )
        print(
            f"  {len(grouped)} bins, sizes {int(grouped['n'].min())}-{int(grouped['n'].max())} "
            f"(target ~{len(oof_proba) // 10}/bin), n_positive per bin {int(grouped['n_positive'].min())}-{int(grouped['n_positive'].max())}"
        )
        print("  reliability (n, n_positive, mean predicted -> actual fraction positive):")
        for i, row in grouped.iterrows():
            print(
                f"    bin {i}: n={int(row['n']):>3} n_positive={int(row['n_positive']):>2} "
                f"predicted~{row['mean_predicted']:.3f} -> actual {row['fraction_positive']:.3f}"
            )
            bin_rows.append(
                {
                    "model": name,
                    "bin": i,
                    "n": int(row["n"]),
                    "n_positive": int(row["n_positive"]),
                    "mean_predicted": float(row["mean_predicted"]),
                    "fraction_positive": float(row["fraction_positive"]),
                }
            )
        summary_rows.append(
            {
                "model": name,
                "brier_score": brier,
                "mean_predicted_probability": mean_pred,
                "actual_prevalence": prevalence,
                "mean_predicted_over_prevalence_ratio": ratio,
            }
        )

    return pd.DataFrame(bin_rows), pd.DataFrame(summary_rows)


def main() -> None:
    print(
        "=" * 78
        + "\nALL numbers below (multi-seed sweep and calibration comparison) come from\n"
        "training-fold out-of-fold predictions - NOT the sealed test set.\n"
        + "=" * 78
    )

    X, y = _train.load_and_clean(_train.DATA_PATH)
    X_tr, X_te, y_tr, _y_te = train_test_split(
        X, y, test_size=TEST_SIZE, stratify=y, random_state=RANDOM_STATE
    )
    # Sanity check only, exactly like 03_train.py: proves a preprocessor
    # fit on the full training fold also handles X_te's shape/categories
    # cleanly. Never used for anything else - X_te's labels (_y_te) are
    # never even loaded into a variable, and this fitted instance is
    # discarded immediately, not reused by the fold-safe pipelines below.
    _train.build_pipeline().fit(X_tr).transform(X_te)

    scale_pos_weight = float((y_tr == 0).sum() / (y_tr == 1).sum())
    plain = _train.build_plain_estimators()
    balanced = _train.build_balanced_estimators(scale_pos_weight)

    # --- 1 & 2: multi-seed threshold sweep + recall-matched comparison ---
    sweep_df = run_multiseed_sweep(X_tr, y_tr, plain)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    multiseed_path = ARTIFACT_DIR / "threshold_sweep_multiseed.csv"
    sweep_df.to_csv(multiseed_path, index=False)
    print(f"\nsaved {len(sweep_df)} rows (4 seeds x 2 models, training-fold OOF) to {multiseed_path}")

    target_df = recall_target_table(sweep_df)
    print("\nper-seed precision at each recall target [training-fold OOF, not test-set]:")
    print(target_df.to_string(index=False, float_format=lambda v: f"{v:.3f}"))

    comparison_table, tally = tally_wins(target_df)
    print("\n12-comparison table (4 seeds x 3 recall targets):")
    print(comparison_table.to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    print(
        f"\nLogReg+SMOTE wins: {tally['logreg_wins']}/12   "
        f"XGBoost+SMOTE wins: {tally['xgboost_wins']}/12   "
        f"ties (|diff|<={TIE_TOLERANCE}): {tally['ties']}/12"
    )

    # --- 3: calibration comparison (separate analysis, single seed) ---
    print("\n" + "=" * 78 + "\nCALIBRATION COMPARISON (separate analysis)\n" + "=" * 78)
    calibration_bins, calibration_summary = calibration_comparison(X_tr, y_tr, plain, balanced)
    calibration_path = ARTIFACT_DIR / "calibration_comparison.csv"
    calibration_bins.merge(calibration_summary, on="model").to_csv(calibration_path, index=False)
    print(f"\nsaved calibration comparison ({len(calibration_bins)} bin-rows) to {calibration_path}")


if __name__ == "__main__":
    main()
