"""Regression suite ONLY (project owner's explicit correction to the
Phase 5 plan). These 30 fixtures are synthetic and hand-built by the
generator that produced fixtures/regression_eval_set/ — a synthetic
generator and the extractor it's tested against inevitably share the same
assumptions about date formats and heading vocabulary, so this cannot
produce an honest accuracy number. It exists to catch code regressions
as field_extractor.py/skill_matcher.py change over time.

The real PRD F3.5 accuracy numbers come from fixtures/real_eval_set/ —
resumes from real public templates, hand-labelled independently by the
project owner — see docs/EVALUATION.md.

Two known exceptions, both on the `name` field, both on two-column PDF
fixtures (resume_008, resume_020): pdfplumber's y-position text join
welds the candidate's name to the sidebar's first line ("Harper Quinn
CONTACT"). This is the same documented, deferred-to-Phase-13 column-
interleaving limitation as Memory.md decision 27 — not a Phase 5 bug —
so these two cases are pinned as known xfail rather than silently
excluded or force-passed. Every other field on both fixtures (email,
phone, education, experience) extracts correctly despite the same
layout, including resume_020's experience_years — the date-range regex
only needs the literal date substring intact, not clean surrounding
prose, so column corruption does not fail every field uniformly.
"""
import json
from datetime import date
from pathlib import Path

import pytest

from app.ml.extraction.field_extractor import extract_all
from app.ml.extraction.text_cleaner import clean_text
from app.ml.extraction.text_extractor import extract_text

FIXTURES = Path(__file__).parent / "fixtures" / "regression_eval_set"
_LABELS = json.loads((FIXTURES / "labels.json").read_text(encoding="utf-8"))
_AS_OF_YEAR, _AS_OF_MONTH = map(int, _LABELS["as_of"].split("-"))
_AS_OF = date(_AS_OF_YEAR, _AS_OF_MONTH, 1)
_ENTRIES = _LABELS["resumes"]
_IDS = [entry["filename"] for entry in _ENTRIES]

_EDUCATION_LEVELS = {"high_school": 1, "associate": 2, "bachelor": 3, "master": 4, "phd": 5, None: None}
_KNOWN_TWO_COLUMN_NAME_CORRUPTION = {"resume_008.pdf", "resume_020.pdf"}


def _extract_fields(filename: str):
    ext = "." + filename.rsplit(".", 1)[1]
    content = (FIXTURES / filename).read_bytes()
    text = clean_text(extract_text(content, ext))
    return extract_all(text, as_of=_AS_OF)


@pytest.fixture(scope="module")
def fields_by_filename():
    return {entry["filename"]: _extract_fields(entry["filename"]) for entry in _ENTRIES}


@pytest.mark.parametrize("entry", _ENTRIES, ids=_IDS)
def test_name_matches_label(entry, fields_by_filename):
    if entry["filename"] in _KNOWN_TWO_COLUMN_NAME_CORRUPTION:
        pytest.xfail(
            "Known two-column PDF limitation, deferred to Phase 13 (Memory.md "
            "decision 27): name gets welded to the sidebar's first line under "
            "pdfplumber's y-position text join."
        )
    actual = fields_by_filename[entry["filename"]].name
    assert (actual or "").lower() == (entry["name"] or "").lower()


@pytest.mark.parametrize("entry", _ENTRIES, ids=_IDS)
def test_email_matches_label(entry, fields_by_filename):
    assert fields_by_filename[entry["filename"]].email == entry["email"]


@pytest.mark.parametrize("entry", _ENTRIES, ids=_IDS)
def test_phone_presence_matches_label(entry, fields_by_filename):
    # Presence/absence only — field_extractor preserves the phone's original
    # punctuation, and this suite deliberately varies formats (dashes,
    # parens, dots, country codes), so exact-string comparison isn't the
    # right check here; test_field_extractor.py covers exact formats.
    actual = fields_by_filename[entry["filename"]].phone
    assert (actual is None) == (entry["phone"] is None)


@pytest.mark.parametrize("entry", _ENTRIES, ids=_IDS)
def test_education_level_matches_label(entry, fields_by_filename):
    expected_level = _EDUCATION_LEVELS[entry["education_level"]]
    assert fields_by_filename[entry["filename"]].education_level == expected_level


@pytest.mark.parametrize("entry", _ENTRIES, ids=_IDS)
def test_experience_years_matches_label(entry, fields_by_filename):
    expected = entry["experience_years"]
    actual = fields_by_filename[entry["filename"]].experience_years
    if expected is None:
        assert actual is None
    else:
        assert actual is not None
        assert abs(actual - expected) <= 1.0


def test_experience_never_returns_zero_across_the_whole_set(fields_by_filename):
    # Whole-suite version of the unit-level check in test_field_extractor.py:
    # 0.0 must never stand in for "couldn't tell" on any of these 30 resumes,
    # including the ones deliberately built with no parseable dates.
    for fields in fields_by_filename.values():
        assert fields.experience_years != 0.0
