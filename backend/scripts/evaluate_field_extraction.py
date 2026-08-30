"""Measures field-extraction accuracy against the REAL, hand-labelled
evaluation set (PRD F3.5) — tests/fixtures/real_eval_set/, resumes from
real public templates with invented details, supplied and hand-labelled
independently by the project owner. This is deliberately NOT the
synthetic regression suite in tests/fixtures/regression_eval_set/ — a
synthetic generator and the extractor it's tested against inevitably
share the same assumptions about date formats and heading vocabulary, so
that suite's numbers are not an honest accuracy measurement and never go
into docs/EVALUATION.md (see the regression suite's own docstring and
Memory.md for the full reasoning).

Grading:
  - name / email: case-insensitive exact match.
  - phone: both sides normalized to digits-only before comparison — the
    extractor preserves the resume's original punctuation, which isn't
    what accuracy should be measured against.
  - education: ordinal ladder level match (data/education.json's levels),
    not a string match.
  - experience_years: extractor's non-None output within ±1.0 year of the
    labelled value; None only counts as correct against a labelled None.

Flags every labels.json entry tagged layout="two_column" where any field
missed — the concrete "possible column-corruption case" list Phase 13
needs (Memory.md decision 27), computed automatically rather than by
manual inspection.

Run manually from backend/ with `python -m scripts.evaluate_field_extraction`.
Writes nothing automatically — docs/EVALUATION.md's methodology section
was written by hand; only its results table is meant to be replaced with
this script's real output once real_eval_set/ exists.
"""
import json
import re
from pathlib import Path

from app.ml.extraction.field_extractor import extract_all
from app.ml.extraction.text_cleaner import clean_text
from app.ml.extraction.text_extractor import extract_text

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "real_eval_set"
LABELS_PATH = FIXTURES_DIR / "labels.json"

_EDUCATION_LEVELS = {"high_school": 1, "associate": 2, "bachelor": 3, "master": 4, "phd": 5, None: None}
_EXPERIENCE_TOLERANCE_YEARS = 1.0
_FIELD_NAMES = ["name", "email", "phone", "education_level", "experience_years"]


def _digits_only(value: str | None) -> str | None:
    return re.sub(r"\D", "", value) if value else None


def _grade_one(entry: dict, actual) -> list[str]:
    """Returns the list of field names that missed for this resume."""
    misses = []

    if (actual.name or "").strip().lower() != (entry["name"] or "").strip().lower():
        misses.append("name")

    if actual.email != entry["email"]:
        misses.append("email")

    if _digits_only(actual.phone) != _digits_only(entry["phone"]):
        misses.append("phone")

    if actual.education_level != _EDUCATION_LEVELS[entry["education_level"]]:
        misses.append("education_level")

    expected_years = entry["experience_years"]
    if expected_years is None:
        years_ok = actual.experience_years is None
    else:
        years_ok = (
            actual.experience_years is not None
            and abs(actual.experience_years - expected_years) <= _EXPERIENCE_TOLERANCE_YEARS
        )
    if not years_ok:
        misses.append("experience_years")

    return misses


def run() -> None:
    if not LABELS_PATH.exists():
        print(
            f"No labelled set found at {FIXTURES_DIR}.\n"
            "This measures accuracy against a REAL, hand-labelled evaluation "
            "set only — it will not run against the synthetic regression "
            "suite. Supply real_eval_set/ (resume files + labels.json) "
            "before running this script."
        )
        return

    labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))["resumes"]
    if not labels:
        print("labels.json has no entries — nothing to evaluate.")
        return

    correct = {f: 0 for f in _FIELD_NAMES}
    two_column_misses: dict[str, list[str]] = {}
    evaluated = 0

    for entry in labels:
        filename = entry["filename"]
        path = FIXTURES_DIR / filename
        if not path.exists():
            print(f"WARNING: {filename} listed in labels.json but not found on disk — skipped.")
            continue

        ext = "." + filename.rsplit(".", 1)[1]
        text = clean_text(extract_text(path.read_bytes(), ext))
        actual = extract_all(text)
        misses = _grade_one(entry, actual)

        evaluated += 1
        for field_name in _FIELD_NAMES:
            if field_name not in misses:
                correct[field_name] += 1

        if misses and entry.get("layout") == "two_column":
            two_column_misses[filename] = misses

    if evaluated == 0:
        print("No labelled resumes were found on disk — nothing evaluated.")
        return

    print(f"\nField extraction accuracy — real evaluation set, n={evaluated}\n")
    for field_name in _FIELD_NAMES:
        rate = correct[field_name] / evaluated * 100
        print(f"  {field_name:20} {correct[field_name]:3}/{evaluated}  ({rate:.1f}%)")

    if two_column_misses:
        print(
            f"\n{len(two_column_misses)} two-column resume(s) had at least one "
            "field miss — possible column-corruption cases for Phase 13:"
        )
        for filename, misses in two_column_misses.items():
            print(f"  {filename}: missed {', '.join(misses)}")
    else:
        print("\nNo two-column resumes had any field miss.")


if __name__ == "__main__":
    run()
