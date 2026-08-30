"""Reusable, serialisable preprocessing pipeline for the attrition dataset.

Feature set and protected-attribute exclusions are documented in
data/README.md and ml/attrition/01_eda.ipynb (PRD F9.1/F9.9). This module
only builds and fits the pipeline; no model is trained here (Phase 10).

Note for callers: this filename starts with a digit ("02_..."), which is not
a valid Python module identifier, so it cannot be imported with a plain
`import` statement. Load it with importlib instead:

    import importlib.util
    spec = importlib.util.spec_from_file_location("attrition_preprocessing", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
"""

from __future__ import annotations

from pathlib import Path

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

NUMERIC_FEATURES = [
    "age",
    "distance_from_home",
    "monthly_income",
    "percent_salary_hike",
    "total_working_years",
    "years_at_company",
    "years_since_last_promotion",
    "years_with_curr_manager",
    "job_level",
    "job_satisfaction",
    "environment_satisfaction",
    "relationship_satisfaction",
    "performance_rating",
    "stock_option_level",
]
CATEGORICAL_FEATURES = ["department", "business_travel"]
BINARY_FEATURE = "overtime"

# Order matches data/README.md's "Feature set" list and the employees table
# (Architecture.md, locked at Phase 8).
FEATURE_COLUMNS = NUMERIC_FEATURES + CATEGORICAL_FEATURES + [BINARY_FEATURE]

# Raw Kaggle column -> employees table column name.
_COLUMN_RENAME = {
    "Age": "age",
    "BusinessTravel": "business_travel",
    "Department": "department",
    "DistanceFromHome": "distance_from_home",
    "EnvironmentSatisfaction": "environment_satisfaction",
    "JobLevel": "job_level",
    "JobSatisfaction": "job_satisfaction",
    "MonthlyIncome": "monthly_income",
    "OverTime": "overtime",
    "PercentSalaryHike": "percent_salary_hike",
    "PerformanceRating": "performance_rating",
    "RelationshipSatisfaction": "relationship_satisfaction",
    "StockOptionLevel": "stock_option_level",
    "TotalWorkingYears": "total_working_years",
    "YearsAtCompany": "years_at_company",
    "YearsSinceLastPromotion": "years_since_last_promotion",
    "YearsWithCurrManager": "years_with_curr_manager",
    "Attrition": "attrition",
}


def load_and_clean(csv_path: str | Path) -> tuple[pd.DataFrame, pd.Series]:
    """Load the raw Kaggle CSV and return the locked feature set plus the label.

    Returns:
        X: DataFrame with exactly FEATURE_COLUMNS, employees-table column names.
        y: Series of 0/1, 1 == attrition.
    Raises:
        ValueError: a raw column this pipeline depends on is missing.
    """
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    missing = set(_COLUMN_RENAME) - set(df.columns)
    if missing:
        raise ValueError(f"raw dataset is missing expected columns: {sorted(missing)}")
    df = df.rename(columns=_COLUMN_RENAME)
    df["overtime"] = (df["overtime"] == "Yes").astype(int)
    y = (df["attrition"] == "Yes").astype(int)
    X = df[FEATURE_COLUMNS].copy()
    return X, y


def build_pipeline() -> Pipeline:
    """Construct the (unfitted) attrition preprocessing pipeline."""
    numeric = Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
        ]
    )
    categorical = Pipeline(
        [
            ("impute", SimpleImputer(strategy="most_frequent")),
            ("encode", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]
    )
    transformer = ColumnTransformer(
        [
            ("numeric", numeric, NUMERIC_FEATURES),
            ("categorical", categorical, CATEGORICAL_FEATURES),
            ("binary", "passthrough", [BINARY_FEATURE]),
        ]
    )
    return Pipeline([("preprocess", transformer)])


def fit_and_save(X: pd.DataFrame, output_path: str | Path) -> Pipeline:
    """Fit the pipeline on X and serialise it to output_path. Returns the fitted pipeline."""
    pipeline = build_pipeline()
    pipeline.fit(X)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, output_path)
    return pipeline


def load_pipeline(path: str | Path) -> Pipeline:
    """Load a previously fitted pipeline from disk."""
    return joblib.load(path)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    data_path = root / "data" / "raw" / "WA_Fn-UseC_-HR-Employee-Attrition.csv"
    artifact_path = Path(__file__).resolve().parent / "artifacts" / "preprocessor.joblib"

    X, y = load_and_clean(data_path)
    pipeline = fit_and_save(X, artifact_path)
    transformed = pipeline.transform(X)
    print(f"fitted on {X.shape[0]} rows, {X.shape[1]} raw features -> {transformed.shape[1]} encoded columns")
    print(f"saved to {artifact_path}")
