"""Read-only threshold validation for SEMANTIC_MATCH_THRESHOLD (Phase 13, F4.4).

Mirrors the EXACT similarity computation already used in production:
- app/ml/skills/skill_gap.py's apply_semantic_fallback(): raw
  sklearn.metrics.pairwise.cosine_similarity on embeddings, compared directly
  against SEMANTIC_MATCH_THRESHOLD (a 0-1 raw cosine value, NOT the *100 scale
  embedding_ranker.py's EmbeddingRanker.score() uses for resume/job scoring).
- app/ml/ranking/embedding_ranker.py's _get_model(): SentenceTransformer(settings.EMBEDDING_MODEL)
  ("all-MiniLM-L6-v2" per backend/.env.example), loaded as a singleton.

This script is read-only: it does not modify the labelling CSV, skill_gap.py,
or any config, and it does not flip THRESHOLD_VALIDATED. It only reads the
completed human labels in semantic_threshold_pairs_labelling_sheet.csv and
reports metrics for a person to review.

Run from anywhere with the project's .venv, e.g.:
    .venv/Scripts/python.exe ml/skill_eval/threshold_validation.py
"""
import csv
import sys
from pathlib import Path

from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

CSV_PATH = Path(__file__).parent / "semantic_threshold_pairs_labelling_sheet.csv"
MODEL_NAME = "all-MiniLM-L6-v2"  # backend/.env.example EMBEDDING_MODEL default


def load_pairs(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def main():
    rows = load_pairs(CSV_PATH)
    print(f"Loaded {len(rows)} rows from CSV.")

    missing_labels = [r["pair_id"] for r in rows if not r["human_match_label"].strip()]
    if missing_labels:
        print(f"STOP: rows missing human_match_label: {missing_labels}")
        sys.exit(1)

    label_map = {}
    for r in rows:
        raw = r["human_match_label"].strip().lower()
        if raw not in ("yes", "no"):
            print(f"STOP: unexpected label {raw!r} for {r['pair_id']} - expected yes/no")
            sys.exit(1)
        label_map[r["pair_id"]] = raw == "yes"

    print("Loading model:", MODEL_NAME)
    model = SentenceTransformer(MODEL_NAME)

    terms_a = [r["term_a"] for r in rows]
    terms_b = [r["term_b"] for r in rows]
    vec_a = model.encode(terms_a)
    vec_b = model.encode(terms_b)

    similarities = {}
    for r, va, vb in zip(rows, vec_a, vec_b):
        sim = float(cosine_similarity([va], [vb])[0][0])
        similarities[r["pair_id"]] = sim

    print("\n--- Per-pair similarity (raw cosine, same scale as SEMANTIC_MATCH_THRESHOLD) ---")
    for r in rows:
        pid = r["pair_id"]
        print(
            f"{pid}  {r['term_a']!r:35s} vs {r['term_b']!r:30s} "
            f"sim={similarities[pid]:.4f}  human={'yes' if label_map[pid] else 'no':3s}  cat={r['category']}"
        )

    print("\n--- Baseline cases ---")
    print(f"P001 AWS -> cloud infrastructure : sim={similarities['P001']:.4f}  human={'yes' if label_map['P001'] else 'no'}")
    print(f"P002 PostgreSQL -> MySQL         : sim={similarities['P002']:.4f}  human={'yes' if label_map['P002'] else 'no'}")

    # Threshold sweep. Only thresholds strictly between consecutive sorted
    # similarity values can change the predicted labels, but midpoints plus
    # the exact values themselves give a fine enough sweep across the
    # relevant range to report accuracy/precision/recall at each distinct
    # decision boundary.
    sims_sorted = sorted(set(similarities.values()))
    candidate_thresholds = set(sims_sorted)
    for i in range(len(sims_sorted) - 1):
        candidate_thresholds.add((sims_sorted[i] + sims_sorted[i + 1]) / 2)
    candidate_thresholds.add(min(sims_sorted) - 0.01)
    candidate_thresholds.add(max(sims_sorted) + 0.01)
    candidate_thresholds = sorted(candidate_thresholds)

    def metrics_at(threshold):
        tp = fp = tn = fn = 0
        fp_ids, fn_ids = [], []
        for pid, sim in similarities.items():
            predicted_match = sim >= threshold
            actual_match = label_map[pid]
            if predicted_match and actual_match:
                tp += 1
            elif predicted_match and not actual_match:
                fp += 1
                fp_ids.append(pid)
            elif not predicted_match and actual_match:
                fn += 1
                fn_ids.append(pid)
            else:
                tn += 1
        n = tp + fp + tn + fn
        accuracy = (tp + tn) / n
        precision = tp / (tp + fp) if (tp + fp) else float("nan")
        recall = tp / (tp + fn) if (tp + fn) else float("nan")
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) and not (precision != precision or recall != recall)
            else float("nan")
        )
        return {
            "threshold": threshold,
            "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "accuracy": accuracy, "precision": precision, "recall": recall, "f1": f1,
            "fp_ids": fp_ids, "fn_ids": fn_ids,
        }

    print("\n--- Threshold sweep (0.0 to 1.0 in 0.05 steps, standard reference grid) ---")
    print(f"{'thr':>6} {'TP':>3} {'FP':>3} {'TN':>3} {'FN':>3} {'acc':>6} {'prec':>6} {'rec':>6} {'f1':>6}")
    t = 0.0
    while t <= 1.001:
        m = metrics_at(round(t, 2))
        print(
            f"{m['threshold']:6.2f} {m['tp']:3d} {m['fp']:3d} {m['tn']:3d} {m['fn']:3d} "
            f"{m['accuracy']:6.3f} {m['precision']:6.3f} {m['recall']:6.3f} {m['f1']:6.3f}"
        )
        t += 0.05

    print("\n--- All candidate decision-boundary thresholds (exact data-driven sweep) ---")
    print(f"{'thr':>8} {'TP':>3} {'FP':>3} {'TN':>3} {'FN':>3} {'acc':>6} {'prec':>6} {'rec':>6} {'f1':>6}   FP_ids / FN_ids")
    all_results = [metrics_at(t) for t in candidate_thresholds]
    for m in all_results:
        print(
            f"{m['threshold']:8.4f} {m['tp']:3d} {m['fp']:3d} {m['tn']:3d} {m['fn']:3d} "
            f"{m['accuracy']:6.3f} {m['precision']:6.3f} {m['recall']:6.3f} {m['f1']:6.3f}   "
            f"FP={m['fp_ids']} FN={m['fn_ids']}"
        )

    perfect = [m for m in all_results if m["fp"] == 0 and m["fn"] == 0]
    print("\n--- Perfect separation check ---")
    if perfect:
        lo = min(m["threshold"] for m in perfect)
        hi = max(m["threshold"] for m in perfect)
        print(f"PERFECT SEPARATION EXISTS for thresholds in [{lo:.4f}, {hi:.4f}]")
    else:
        print("NO threshold achieves perfect separation (0 FP and 0 FN simultaneously).")

    best_acc = max(all_results, key=lambda m: (m["accuracy"], -abs(m["threshold"] - 0.5)))
    best_f1 = max(all_results, key=lambda m: (m["f1"] if m["f1"] == m["f1"] else -1, -abs(m["threshold"] - 0.5)))
    print("\n--- Best threshold by accuracy ---")
    print(best_acc)
    print("\n--- Best threshold by F1 ---")
    print(best_f1)


if __name__ == "__main__":
    main()
