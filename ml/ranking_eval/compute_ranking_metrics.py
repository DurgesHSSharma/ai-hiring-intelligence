"""Phase 13 / F14.1 — ranking relevance metrics (Precision@K, Recall@K,
NDCG) for the TF-IDF and embedding rankers, against the 51-pair human
gold standard in ranking_pairs_labelling_sheet.csv (3 jobs x 17
candidates, graded 0-3).

Read-only end to end: reads the labelling CSV and the 42 underlying
resume fixtures, and calls the real production functions unmodified.
Writes nothing back to the CSV or any production file — prints a report
to stdout only.

Reuses the actual production implementations, not an approximation:
  - backend/app/ml/extraction/text_extractor.py :: extract_text()
  - backend/app/ml/ranking/factory.py           :: get_ranker()
  - backend/app/ml/ranking/tfidf_ranker.py       :: TFIDFRanker
  - backend/app/ml/ranking/embedding_ranker.py   :: EmbeddingRanker

Replicates scoring_service.py's exact usage pattern for both rankers
(see scoring_service.py:378-389,304): one ranker instance per job,
fit() once on [job.description] + every candidate's resume_text for
that job, then score(resume_text, job.description) per candidate.
"""
import csv
import math
import os
import sys
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")  # model already cached locally; no network needed

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
BACKEND_ROOT = REPO_ROOT / "backend"
CSV_PATH = SCRIPT_DIR / "ranking_pairs_labelling_sheet.csv"

sys.path.insert(0, str(BACKEND_ROOT))

from app.ml.extraction.text_extractor import extract_text  # noqa: E402
from app.ml.ranking.factory import get_ranker  # noqa: E402

RANKER_MODES = ["tfidf", "embedding"]
RELEVANT_THRESHOLD = 2  # grades 2-3 = relevant, 0-1 = not relevant
RECALL_K = 10  # Recall@10, paired with Precision@10


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


def dcg(grades_in_rank_order: list[int], k: int | None = None) -> float:
    """Standard exponential-gain DCG: sum (2^rel - 1) / log2(rank + 1),
    1-indexed rank. k=None means the full list.
    """
    seq = grades_in_rank_order if k is None else grades_in_rank_order[:k]
    return sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(seq))


def ndcg(ranked_grades: list[int]) -> float:
    """Full-list NDCG (no cutoff): DCG of the produced ranking divided by
    the DCG of the ideal ranking (grades sorted descending).
    """
    ideal = sorted(ranked_grades, reverse=True)
    idcg = dcg(ideal)
    if idcg == 0:
        return float("nan")
    return dcg(ranked_grades) / idcg


def precision_at_k(ranked_relevant: list[bool], k: int) -> float:
    top_k = ranked_relevant[:k]
    return sum(top_k) / k


def recall_at_k(ranked_relevant: list[bool], k: int, total_relevant: int) -> float:
    if total_relevant == 0:
        return float("nan")
    top_k = ranked_relevant[:k]
    return sum(top_k) / total_relevant


def evaluate_job(job_rows: list[dict], mode: str) -> dict:
    job_text = job_rows[0]["job_description"]
    assert all(r["job_description"] == job_text for r in job_rows), "job_description differs within a job group"

    resume_texts = [get_resume_text(r["candidate_source_file"]) for r in job_rows]
    grades = [int(r["human_relevance_label"]) for r in job_rows]
    pair_ids = [r["pair_id"] for r in job_rows]

    ranker = get_ranker(method=mode)
    corpus = [job_text] + resume_texts
    ranker.fit(corpus)
    scores = [ranker.score(text, job_text) for text in resume_texts]

    order = sorted(range(len(job_rows)), key=lambda i: (-scores[i], i))  # stable: ties keep original CSV order
    ranked_pair_ids = [pair_ids[i] for i in order]
    ranked_scores = [scores[i] for i in order]
    ranked_grades = [grades[i] for i in order]
    ranked_relevant = [g >= RELEVANT_THRESHOLD for g in ranked_grades]

    total_relevant = sum(1 for g in grades if g >= RELEVANT_THRESHOLD)
    total_nonzero = sum(1 for g in grades if g > 0)

    return {
        "mode": mode,
        "ranked_pair_ids": ranked_pair_ids,
        "ranked_scores": ranked_scores,
        "ranked_grades": ranked_grades,
        "total_relevant": total_relevant,
        "total_nonzero": total_nonzero,
        "n_candidates": len(job_rows),
        "precision_at_5": precision_at_k(ranked_relevant, 5),
        "precision_at_10": precision_at_k(ranked_relevant, 10),
        f"recall_at_{RECALL_K}": recall_at_k(ranked_relevant, RECALL_K, total_relevant),
        "ndcg": ndcg(ranked_grades),
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

    print("=" * 88)
    print("JOB / LABEL COMPOSITION (ground truth, independent of ranker)")
    print("=" * 88)
    for jid in job_ids:
        grades = [int(r["human_relevance_label"]) for r in jobs[jid]]
        title = jobs[jid][0]["job_title"]
        nonzero = sum(1 for g in grades if g > 0)
        relevant = sum(1 for g in grades if g >= RELEVANT_THRESHOLD)
        print(
            f"Job {jid} ({title}): 17 candidates | non-zero grade (>0): {nonzero} "
            f"| relevant (grade>=2): {relevant} | grade distribution: {sorted(grades, reverse=True)}"
        )

    print()
    print(f"Relevance threshold for Precision/Recall: grade >= {RELEVANT_THRESHOLD} = relevant")
    print(f"Recall@K uses K = {RECALL_K}")
    print("NDCG is full-list (all 17 candidates, no cutoff), exponential-gain formula, using raw 0-3 grades")

    results = {mode: {} for mode in RANKER_MODES}
    for jid in job_ids:
        for mode in RANKER_MODES:
            results[mode][jid] = evaluate_job(jobs[jid], mode)

    for jid in job_ids:
        title = jobs[jid][0]["job_title"]
        print()
        print("=" * 88)
        print(f"JOB {jid} ({title}) - RANKED ORDER (best to worst) PER RANKER")
        print("=" * 88)
        for mode in RANKER_MODES:
            r = results[mode][jid]
            print(f"\n[{mode}] ranked pair_ids (score, grade):")
            for pid, score, grade in zip(r["ranked_pair_ids"], r["ranked_scores"], r["ranked_grades"]):
                mark = "RELEVANT" if grade >= RELEVANT_THRESHOLD else ""
                print(f"  {pid}  score={score:6.2f}  grade={grade}  {mark}")

    print()
    print("=" * 88)
    print("PER-JOB METRICS, TF-IDF vs EMBEDDING (side by side)")
    print("=" * 88)
    header = (
        f"{'Job':6} {'Method':10} {'P@5':>8} {'P@10':>8} "
        f"{'R@' + str(RECALL_K):>8} {'NDCG':>8}"
    )
    print(header)
    for jid in job_ids:
        for mode in RANKER_MODES:
            r = results[mode][jid]
            print(
                f"{jid:6} {mode:10} {r['precision_at_5']:8.3f} {r['precision_at_10']:8.3f} "
                f"{r[f'recall_at_{RECALL_K}']:8.3f} {r['ndcg']:8.3f}"
            )

    print()
    print("=" * 88)
    print("AVERAGED ACROSS JOBS (simple mean of the 3 per-job values)")
    print("=" * 88)
    print(f"{'Method':10} {'P@5':>8} {'P@10':>8} {'R@' + str(RECALL_K):>8} {'NDCG':>8}")
    for mode in RANKER_MODES:
        p5 = sum(results[mode][j]["precision_at_5"] for j in job_ids) / len(job_ids)
        p10 = sum(results[mode][j]["precision_at_10"] for j in job_ids) / len(job_ids)
        r10 = sum(results[mode][j][f"recall_at_{RECALL_K}"] for j in job_ids) / len(job_ids)
        ndcgs = [results[mode][j]["ndcg"] for j in job_ids]
        ndcg_avg = sum(ndcgs) / len(ndcgs)
        print(f"{mode:10} {p5:8.3f} {p10:8.3f} {r10:8.3f} {ndcg_avg:8.3f}")

    print()
    print("=" * 88)
    print("SPARSE-POOL CAVEAT (per job)")
    print("=" * 88)
    for jid in job_ids:
        r_any = results[RANKER_MODES[0]][jid]
        print(
            f"Job {jid}: {r_any['total_nonzero']} non-zero-grade candidates, "
            f"{r_any['total_relevant']} relevant (grade>=2) out of 17. "
            f"Precision@10 denominator (10) exceeds the relevant pool size "
            f"({r_any['total_relevant']}) here, so Precision@10 is bounded well "
            f"below 1.0 by data sparsity, not necessarily by ranker quality."
        )

    print()
    print("=" * 88)
    print("SELF-CHECK")
    print("=" * 88)
    print(f"exactly 3 jobs x 17 candidates evaluated: {len(job_ids) == 3 and all(len(jobs[j]) == 17 for j in job_ids)}")
    print(f"both ranker modes evaluated: {RANKER_MODES}")


if __name__ == "__main__":
    main()
