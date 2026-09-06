"""Phase 13 / F14.2 — skill-extraction precision/recall/F1 against the
30-resume human gold standard in skill_list_labelling_sheet.csv.

Read-only end to end: reads the labelling CSV and data/skills.json, reads
the 30 source resumes, and calls the real production extraction + matching
functions unmodified. Writes nothing back to the CSV, skills.json, or any
production file — this script only prints a report to stdout.

Reuses the actual production implementations, not an approximation:
  - backend/app/ml/extraction/text_extractor.py :: extract_text()
  - backend/app/ml/skills/skill_matcher.py      :: match_skills()

`data/skills.json` is also read directly here, but only to classify a
missed gold skill as a known-vocabulary miss vs. a vocabulary-coverage
miss (Category A/B below) — never to influence what counts as a
prediction. Predictions come solely from match_skills().
"""
import csv
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
BACKEND_ROOT = REPO_ROOT / "backend"
CSV_PATH = SCRIPT_DIR / "skill_list_labelling_sheet.csv"
SKILLS_JSON_PATH = BACKEND_ROOT / "app" / "data" / "skills.json"

sys.path.insert(0, str(BACKEND_ROOT))

from app.ml.extraction.text_extractor import extract_text  # noqa: E402
from app.ml.skills.skill_matcher import match_skills  # noqa: E402

EXPECTED_IDS = [f"S{n:03d}" for n in range(1, 31)]

FREE_TEXT_NOTE_RE = re.compile(r"free-text fallback:\s*(.+)$", re.IGNORECASE)


def load_vocab():
    raw = json.loads(SKILLS_JSON_PATH.read_text(encoding="utf-8"))
    canonical_lower = set()
    alias_lower = set()
    for entry in raw["skills"]:
        canonical_lower.add(entry["canonical"].lower())
        for alias in entry["aliases"]:
            alias_lower.add(alias.lower())
    return canonical_lower, alias_lower


def has_vocab_entry(term: str, canonical_lower: set, alias_lower: set) -> bool:
    t = term.lower()
    return t in canonical_lower or t in alias_lower


def parse_free_text_notes(human_notes: str) -> set:
    match = FREE_TEXT_NOTE_RE.search(human_notes or "")
    if not match:
        return set()
    return {t.strip().lower() for t in match.group(1).split(";") if t.strip()}


def load_rows():
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    ids = [r["resume_id"] for r in rows]
    if ids != EXPECTED_IDS:
        print(f"STOP: expected exactly {EXPECTED_IDS}, got {ids}")
        sys.exit(1)
    return rows


def predict_skills(source_file: str) -> set:
    """Runs the real production path: extract_text() then match_skills().
    Returns the set of predicted canonical skill names, lowercased for
    comparison, mapped back to their real canonical casing.
    """
    full_path = REPO_ROOT / source_file
    if not full_path.exists():
        print(f"STOP: missing source file {full_path}")
        sys.exit(1)
    content = full_path.read_bytes()
    text = extract_text(content, full_path.suffix)
    matches = match_skills(text)
    return {m.canonical.lower(): m.canonical for m in matches}


def main():
    canonical_lower, alias_lower = load_vocab()
    rows = load_rows()

    per_resume = []
    all_fn = []  # (resume_id, skill, category, reason)
    all_fp = []  # (resume_id, skill, note)

    total_gold = total_pred = total_tp = total_fp = total_fn = 0

    for row in rows:
        rid = row["resume_id"]
        gold_terms = {t.strip() for t in row["gold_skills"].split(";") if t.strip()}
        gold_lower = {t.lower(): t for t in gold_terms}

        predicted_lower = predict_skills(row["source_file"])

        gold_set = set(gold_lower.keys())
        pred_set = set(predicted_lower.keys())

        tp_set = gold_set & pred_set
        fn_set = gold_set - pred_set
        fp_set = pred_set - gold_set

        tp, fp, fn = len(tp_set), len(fp_set), len(fn_set)
        precision = tp / (tp + fp) if (tp + fp) else float("nan")
        recall = tp / (tp + fn) if (tp + fn) else float("nan")
        f1 = (
            2 * precision * recall / (precision + recall)
            if (tp + fp) and (tp + fn) and (precision + recall) > 0
            else float("nan")
        )

        per_resume.append(
            {
                "resume_id": rid,
                "gold_count": len(gold_set),
                "pred_count": len(pred_set),
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "precision": precision,
                "recall": recall,
                "f1": f1,
            }
        )

        total_gold += len(gold_set)
        total_pred += len(pred_set)
        total_tp += tp
        total_fp += fp
        total_fn += fn

        free_text_noted = parse_free_text_notes(row["human_notes"])

        for term_lower in fn_set:
            term = gold_lower[term_lower]
            vocab_hit = has_vocab_entry(term, canonical_lower, alias_lower)
            noted_free_text = term_lower in free_text_noted

            if noted_free_text and vocab_hit:
                print(
                    f"STOP: categorisation bug — {rid}'s FREE_TEXT term "
                    f"{term!r} unexpectedly has a canonical/alias entry in "
                    f"skills.json. A FREE_TEXT term must never be Category A."
                )
                sys.exit(1)

            if vocab_hit:
                category = "A"
                reason = "has a canonical entry or alias in skills.json — matcher failed to find it in the resume text"
            elif noted_free_text:
                category = "B"
                reason = "recorded FREE_TEXT fallback in human_notes; no canonical/alias entry exists in skills.json"
            else:
                category = "UNCLASSIFIED"
                reason = (
                    "no canonical/alias entry in skills.json, but NOT recorded as a "
                    "free-text fallback in human_notes — data anomaly, not A or B"
                )
            all_fn.append((rid, term, category, reason))

        for term_lower in fp_set:
            term = predicted_lower[term_lower]
            if rid in ("S003", "S018") and term_lower == "machine learning":
                note = (
                    "evaluator/gold-standard disagreement, NOT an extractor defect: "
                    "the resume describes ML activity without explicitly naming the "
                    "skill 'Machine Learning', so it was deliberately excluded from "
                    "gold; the matcher credits it anyway"
                )
            else:
                note = "predicted by the matcher but not in the gold standard for this resume - review whether this is a matcher over-match or a conservative gold omission"
            all_fp.append((rid, term, note))

    overall_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else float("nan")
    overall_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else float("nan")
    overall_f1 = (
        2 * overall_precision * overall_recall / (overall_precision + overall_recall)
        if (overall_precision + overall_recall) > 0
        else float("nan")
    )

    print("=" * 80)
    print("B. OVERALL METRICS")
    print("=" * 80)
    print(f"resumes evaluated : {len(rows)}")
    print(f"total gold skills : {total_gold}")
    print(f"total predicted   : {total_pred}")
    print(f"TP                : {total_tp}")
    print(f"FP                : {total_fp}")
    print(f"FN                : {total_fn}")
    print(f"precision (micro) : {overall_precision:.4f}")
    print(f"recall (micro)    : {overall_recall:.4f}")
    print(f"F1 (micro)        : {overall_f1:.4f}")

    print()
    print("=" * 80)
    print("C. PER-RESUME METRICS")
    print("=" * 80)
    header = f"{'S-ID':6} {'gold':>4} {'pred':>4} {'TP':>3} {'FP':>3} {'FN':>3} {'prec':>7} {'rec':>7} {'f1':>7}"
    print(header)
    for m in per_resume:
        print(
            f"{m['resume_id']:6} {m['gold_count']:>4} {m['pred_count']:>4} "
            f"{m['tp']:>3} {m['fp']:>3} {m['fn']:>3} "
            f"{m['precision']:>7.3f} {m['recall']:>7.3f} {m['f1']:>7.3f}"
        )

    print()
    print("=" * 80)
    print("D. FALSE NEGATIVE CLASSIFICATION")
    print("=" * 80)
    cat_a = [x for x in all_fn if x[2] == "A"]
    cat_b = [x for x in all_fn if x[2] == "B"]
    cat_other = [x for x in all_fn if x[2] not in ("A", "B")]
    total_fn_listed = len(all_fn)
    pct_a = (len(cat_a) / total_fn_listed * 100) if total_fn_listed else 0.0
    pct_b = (len(cat_b) / total_fn_listed * 100) if total_fn_listed else 0.0
    pct_other = (len(cat_other) / total_fn_listed * 100) if total_fn_listed else 0.0
    print(f"known-vocabulary FN (Category A)   : {len(cat_a)}  ({pct_a:.1f}% of all FNs)")
    print(f"vocabulary-coverage FN (Category B): {len(cat_b)}  ({pct_b:.1f}% of all FNs)")
    if cat_other:
        print(f"UNCLASSIFIED (data anomaly)        : {len(cat_other)}  ({pct_other:.1f}% of all FNs)")
    print()
    print(f"{'S-ID':6} | {'missed skill':35} | {'category':7} | reason")
    for rid, term, category, reason in all_fn:
        print(f"{rid:6} | {term:35} | {category:7} | {reason}")

    print()
    print("=" * 80)
    print("E. FALSE POSITIVE LIST")
    print("=" * 80)
    print(f"{'S-ID':6} | {'predicted skill':30} | note")
    for rid, term, note in all_fp:
        print(f"{rid:6} | {term:30} | {note}")

    print()
    print("=" * 80)
    print("S008 / S020 CORRUPTED-PDF RECALL CHECK")
    print("=" * 80)
    for target in ("S008", "S020"):
        m = next(x for x in per_resume if x["resume_id"] == target)
        fns_here = [f"{term}" for rid, term, cat, reason in all_fn if rid == target]
        print(
            f"{target}: recall={m['recall']:.3f} gold={m['gold_count']} "
            f"tp={m['tp']} fn={m['fn']}  missed_gold_skills={fns_here or 'NONE'}"
        )

    print()
    print("=" * 80)
    print("SELF-CHECK")
    print("=" * 80)
    print(f"exactly 30 resumes evaluated : {len(rows) == 30}")
    print(f"S001-S030 all present        : {[r['resume_id'] for r in rows] == EXPECTED_IDS}")


if __name__ == "__main__":
    main()
