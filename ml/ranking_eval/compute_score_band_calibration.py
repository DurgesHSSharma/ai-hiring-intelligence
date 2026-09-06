"""Phase 13 / F7.5 - score-band calibration study.

Evaluates whether the current, uncalibrated score-band thresholds
(85=strong, 70=good, 55=moderate, else weak -- scoring_service.py's
_BAND_THRESHOLDS) produce consistent candidate bands between the two
production scoring methods (tfidf, embedding), against the 51-pair human
relevance gold standard in ranking_pairs_labelling_sheet.csv.

This is a DESCRIPTIVE CALIBRATION STUDY ONLY:
  - it does not modify _BAND_THRESHOLDS, any ranker, or any production file
  - it proposes candidate thresholds for a person to review, but adopts none
  - "proposed" and "adopted in production" are reported as separate,
    explicitly labelled things -- see the final report section

Read-only end to end. Reuses real production functions unmodified, not an
approximation of them:
  - app/ml/extraction/text_extractor.py  :: extract_text()
  - app/ml/extraction/field_extractor.py :: extract_education()
  - app/ml/ranking/factory.py            :: get_ranker()
  - app/ml/skills/skill_gap.py           :: compute_skill_gap()
  - app/services/scoring_service.py      :: _experience_score(),
        _education_score(), _compose_final_score(), _compute_band(),
        _BAND_THRESHOLDS (imported, never reassigned)

Replicates scoring_service.py's exact per-job scoring pattern: one ranker
instance per job, fit() once on [job.description] + every candidate's
resume_text for that job, then score(resume_text, job.description) per
candidate (see scoring_service.py:378-389,304), followed by the same
skill/experience/education sub-scores and the same weighted composition
(scoring_service.py:252-276) used to reach final_fit_score, which is what
_compute_band() actually operates on in production -- not the raw
resume_match alone.
"""
import csv
import os
import sys
from collections import Counter
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")  # model already cached locally; no network needed

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
BACKEND_ROOT = REPO_ROOT / "backend"
CSV_PATH = SCRIPT_DIR / "ranking_pairs_labelling_sheet.csv"

sys.path.insert(0, str(BACKEND_ROOT))

from app.core.enums import ScoreBand  # noqa: E402
from app.ml.extraction.field_extractor import extract_education  # noqa: E402
from app.ml.extraction.text_extractor import extract_text  # noqa: E402
from app.ml.ranking.factory import get_ranker  # noqa: E402
from app.ml.skills.skill_gap import compute_skill_gap  # noqa: E402
from app.services.scoring_service import (  # noqa: E402
    _BAND_THRESHOLDS,
    _compose_final_score,
    _compute_band,
    _education_score,
    _experience_score,
)

RANKER_MODES = ["tfidf", "embedding"]
BAND_ORDER = [ScoreBand.STRONG_MATCH, ScoreBand.GOOD_MATCH, ScoreBand.MODERATE_MATCH, ScoreBand.WEAK_MATCH]
RELEVANT_THRESHOLD = 2  # same convention as compute_ranking_metrics.py: grade>=2 = relevant


def split_semicolon(value: str) -> list[str]:
    return [v.strip() for v in value.split(";") if v.strip()]


def parse_float_or_none(value: str) -> float | None:
    value = value.strip()
    return float(value) if value else None


def load_rows():
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    expected_pairs = [f"R{n:03d}" for n in range(1, 52)]
    actual_pairs = [r["pair_id"] for r in rows]
    if actual_pairs != expected_pairs:
        print(f"STOP: expected exactly {expected_pairs}, got {actual_pairs}")
        sys.exit(1)
    return rows


_text_cache: dict[str, str] = {}


def get_resume_text(source_file: str) -> str:
    if source_file in _text_cache:
        return _text_cache[source_file]
    full_path = REPO_ROOT / source_file
    if not full_path.exists():
        print(f"STOP: missing source file {full_path}")
        sys.exit(1)
    content = full_path.read_bytes()
    try:
        text = extract_text(content, full_path.suffix)
    except Exception as exc:
        print(f"STOP: unreadable file {full_path} ({exc})")
        sys.exit(1)
    _text_cache[source_file] = text
    return text


def method_independent_subscores(row: dict, required_level: int | None) -> dict:
    """skill_match, experience_score, education_score never depend on which
    ranker is used -- only resume_match/final_fit_score do. Computed once
    per candidate and reused for both scoring methods.
    """
    required_skills = split_semicolon(row["job_required_skills"])
    candidate_skills = split_semicolon(row["candidate_extracted_skills"])
    gap = compute_skill_gap(required_skills, candidate_skills)
    skill_match = round(gap.percentage, 1)

    experience_years = parse_float_or_none(row["candidate_experience_years"])
    required_years = float(row["job_min_experience_years"])
    experience_score = _experience_score(experience_years, required_years)

    candidate_education_text = row["candidate_education"].strip()
    candidate_level = extract_education(candidate_education_text)[1] if candidate_education_text else None
    education_score = _education_score(candidate_level, required_level)

    return {
        "skill_match": skill_match,
        "experience_score": experience_score,
        "education_score": education_score,
    }


def main():
    rows = load_rows()
    jobs = {}
    for r in rows:
        jobs.setdefault(r["job_id"], []).append(r)
    job_ids = sorted(jobs.keys(), key=int)
    if len(job_ids) != 3 or any(len(jobs[j]) != 17 for j in job_ids):
        print(f"STOP: expected 3 jobs x 17 candidates, got {[(j, len(jobs[j])) for j in job_ids]}")
        sys.exit(1)

    print("=" * 92)
    print("PRODUCTION BAND THRESHOLDS IN USE (unmodified, imported from scoring_service.py)")
    print("=" * 92)
    for threshold, band in _BAND_THRESHOLDS:
        print(f"  final_fit_score >= {threshold:5.1f} -> {band.value}")
    print(f"  else -> {ScoreBand.WEAK_MATCH.value}")

    # per-candidate record, keyed by pair_id
    records: dict[str, dict] = {}

    for jid in job_ids:
        job_rows = jobs[jid]
        job_text = job_rows[0]["job_description"]
        assert all(r["job_description"] == job_text for r in job_rows)
        required_level = extract_education(job_rows[0]["job_education_requirement"])[1]

        sub_by_pair = {r["pair_id"]: method_independent_subscores(r, required_level) for r in job_rows}
        resume_texts = [get_resume_text(r["candidate_source_file"]) for r in job_rows]

        for mode in RANKER_MODES:
            ranker = get_ranker(method=mode)
            corpus = [job_text] + resume_texts
            ranker.fit(corpus)
            for r, resume_text in zip(job_rows, resume_texts):
                pid = r["pair_id"]
                resume_match = round(ranker.score(resume_text, job_text), 1)
                sub = sub_by_pair[pid]
                final_fit_score = _compose_final_score(
                    resume_match, sub["skill_match"], sub["experience_score"], sub["education_score"]
                )
                band = _compute_band(final_fit_score)
                records.setdefault(pid, {"job_id": jid, "grade": int(r["human_relevance_label"])})
                records[pid][mode] = {
                    "resume_match": resume_match,
                    "skill_match": sub["skill_match"],
                    "experience_score": sub["experience_score"],
                    "education_score": sub["education_score"],
                    "final_fit_score": final_fit_score,
                    "band": band,
                }

    pair_ids_sorted = [f"R{n:03d}" for n in range(1, 52)]

    print()
    print("=" * 92)
    print("PER-CANDIDATE DETAIL (final_fit_score and band, both methods)")
    print("=" * 92)
    header = (
        f"{'pair':6} {'job':4} {'grade':5} | "
        f"{'tfidf_ffs':>10} {'tfidf_band':>14} | "
        f"{'emb_ffs':>10} {'emb_band':>14} | agree?"
    )
    print(header)
    for pid in pair_ids_sorted:
        rec = records[pid]
        t = rec["tfidf"]
        e = rec["embedding"]
        agree = "yes" if t["band"] == e["band"] else "NO"
        print(
            f"{pid:6} {rec['job_id']:4} {rec['grade']:5} | "
            f"{t['final_fit_score']:10.1f} {t['band'].value:>14} | "
            f"{e['final_fit_score']:10.1f} {e['band'].value:>14} | {agree}"
        )

    print()
    print("=" * 92)
    print("5. BAND DISTRIBUTION BY SCORING METHOD (all 51 pairs)")
    print("=" * 92)
    for mode in RANKER_MODES:
        counts = Counter(records[pid][mode]["band"] for pid in pair_ids_sorted)
        line = "  ".join(f"{b.value}={counts.get(b, 0)}" for b in BAND_ORDER)
        print(f"{mode:10}: {line}")

    print()
    print("=" * 92)
    print("6. GRADE (0-3) x BAND CROSS-TAB, PER METHOD")
    print("=" * 92)
    for mode in RANKER_MODES:
        print(f"\n[{mode}]")
        header = f"{'grade':6} " + " ".join(f"{b.value:>14}" for b in BAND_ORDER)
        print(header)
        for grade in (3, 2, 1, 0):
            counts = Counter(records[pid][mode]["band"] for pid in pair_ids_sorted if records[pid]["grade"] == grade)
            row_str = f"{grade:6} " + " ".join(f"{counts.get(b, 0):>14}" for b in BAND_ORDER)
            print(row_str)

    print()
    print("=" * 92)
    print("7. IDENTICAL CANDIDATE, DIFFERENT BAND BETWEEN TF-IDF AND EMBEDDING")
    print("=" * 92)
    disagreements = [pid for pid in pair_ids_sorted if records[pid]["tfidf"]["band"] != records[pid]["embedding"]["band"]]
    print(f"{len(disagreements)} of 51 pairs land in a DIFFERENT band depending on scoring method alone:\n")
    for pid in disagreements:
        rec = records[pid]
        t, e = rec["tfidf"], rec["embedding"]
        print(
            f"  {pid} (job {rec['job_id']}, human grade={rec['grade']}): "
            f"tfidf={t['final_fit_score']:.1f}/{t['band'].value}  "
            f"embedding={e['final_fit_score']:.1f}/{e['band'].value}"
        )
    if not disagreements:
        print("  (none)")

    print()
    print("=" * 92)
    print("8. DESCRIPTIVE THRESHOLD-SEPARATION CHECK (evidence only, nothing adopted)")
    print("=" * 92)
    for mode in RANKER_MODES:
        relevant_scores = sorted(
            records[pid][mode]["final_fit_score"] for pid in pair_ids_sorted if records[pid]["grade"] >= RELEVANT_THRESHOLD
        )
        not_relevant_scores = sorted(
            records[pid][mode]["final_fit_score"] for pid in pair_ids_sorted if records[pid]["grade"] < RELEVANT_THRESHOLD
        )
        print(f"\n[{mode}] final_fit_score, relevant (grade>=2) candidates (n={len(relevant_scores)}):")
        print(f"  {relevant_scores}")
        print(f"[{mode}] final_fit_score, NOT relevant (grade<=1) candidates (n={len(not_relevant_scores)}):")
        print(f"  min={min(not_relevant_scores):.1f} max={max(not_relevant_scores):.1f} "
              f"(full list omitted, {len(not_relevant_scores)} values)")
        if relevant_scores and not_relevant_scores:
            overlap = min(relevant_scores) <= max(not_relevant_scores)
            print(
                f"[{mode}] relevant range [{min(relevant_scores):.1f}, {max(relevant_scores):.1f}] vs "
                f"not-relevant range [{min(not_relevant_scores):.1f}, {max(not_relevant_scores):.1f}] "
                f"-> {'OVERLAP (no clean separating threshold exists)' if overlap else 'cleanly separable'}"
            )

    print()
    print("=" * 92)
    print("SAMPLE-SIZE CAVEAT")
    print("=" * 92)
    n_relevant_total = sum(1 for pid in pair_ids_sorted if records[pid]["grade"] >= RELEVANT_THRESHOLD)
    print(
        f"Only {n_relevant_total} of 51 labelled pairs are 'relevant' (grade>=2) in total, "
        f"across all 3 jobs. Any threshold derived from this set is a starting hypothesis, "
        f"not a statistically robust recalibration -- see the final written report for the "
        f"explicit descriptive-vs-proposed-vs-adopted distinction."
    )

    print()
    print("=" * 92)
    print("SELF-CHECK")
    print("=" * 92)
    print(f"exactly 3 jobs x 17 candidates evaluated: {len(job_ids) == 3 and all(len(jobs[j]) == 17 for j in job_ids)}")
    print(f"both scoring methods evaluated: {RANKER_MODES}")
    print(f"_BAND_THRESHOLDS unmodified (imported, never reassigned): {_BAND_THRESHOLDS}")


if __name__ == "__main__":
    main()
