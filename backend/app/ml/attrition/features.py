"""Serving-time feature construction (Phases.md Phase 11). Converts a
validated prediction input into the exact ordered raw feature row
predictor.py's artifacts expect - never fills a missing business value with
a guess (Rules.md 4.6/5.4: "Never silently fill missing business features
with arbitrary values").
"""
from __future__ import annotations

import pandas as pd

from app.core.exceptions import ValidationError

# Phase 9 excluded these from the model for fairness (data/README.md,
# Rules.md 7 / F9.9). Never read from the payload below, regardless of what
# a caller supplies: this module only ever looks up names present in
# `feature_names` (the loaded artifact's canonical list), and none of these
# three is ever one of them - see the assertion in build_feature_row(),
# which would fail loudly if that ever stopped being true.
PROTECTED_ATTRIBUTES = frozenset({"gender", "marital_status", "over18"})


def build_feature_row(payload: object, feature_names: list[str]) -> pd.DataFrame:
    """payload is a Pydantic model exposing one attribute per business
    feature (schemas.attrition.EmployeeFeaturesIn or a subclass), each
    Optional and defaulting to None when not supplied - so a missing field
    never trips FastAPI's own 422 before this function gets a chance to
    name it specifically, per Phases.md Phase 11's explicit requirement.

    feature_names is the canonical, ordered list from the loaded artifact
    (predictor.get_artifacts().feature_names, i.e. feature_names.json) -
    not a hardcoded duplicate, so this can never silently drift from what
    the model was actually trained on.

    Raises:
        ValidationError(code="INVALID_FEATURE_SET"): one or more required
            features are missing, naming exactly which.
    """
    assert not PROTECTED_ATTRIBUTES & set(feature_names), (
        "a protected attribute leaked into the canonical feature list - "
        "this must never happen; see data/README.md and Rules.md 7"
    )

    values = payload.model_dump()
    missing = [name for name in feature_names if values.get(name) is None]
    if missing:
        raise ValidationError(
            f"Missing required attrition feature(s): {', '.join(missing)}.",
            code="INVALID_FEATURE_SET",
            details={"missing_features": missing},
        )

    row = {name: values[name] for name in feature_names}
    if "overtime" in row:
        # Matches ml/attrition/02_preprocessing.py's load_and_clean(): OverTime
        # is encoded as an int 0/1 before the model ever sees it, not a bool
        # or a "Yes"/"No" string.
        row["overtime"] = int(bool(row["overtime"]))

    feature_row = pd.DataFrame([row], columns=feature_names)

    # Train-serve skew guard (Phases.md Phase 11): the row just built must
    # have exactly as many columns as the canonical feature list it was
    # built from - real protection against a future edit to this function
    # silently adding, dropping, or renaming a column. The corresponding
    # check that feature_names.json itself still matches what
    # preprocessor.joblib/model.joblib actually expect runs once at
    # artifact-load time (predictor.load_artifacts()), not per request.
    if feature_row.shape[1] != len(feature_names):
        raise ValidationError(
            "Constructed feature row does not match the canonical feature "
            f"count: expected {len(feature_names)}, got {feature_row.shape[1]}.",
            code="INVALID_FEATURE_SET",
            details={"expected_width": len(feature_names), "actual_width": feature_row.shape[1]},
        )

    return feature_row
