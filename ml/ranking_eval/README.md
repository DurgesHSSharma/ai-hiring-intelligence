# Ranking evaluation — human-labelling package (Phase 13, F14.1)

**Status: final labelling sheet prepared, unlabelled. No metric has been computed. No code has been changed.**

This package supports Phases.md Phase 13's ranking-evaluation build item:
a labelled relevance set of at least 50 candidate/job pairs, used to
compute Precision@5, Precision@10, Recall@K, and NDCG, comparing the
TF-IDF ranker (`app/ml/ranking/tfidf_ranker.py`) against the embedding
ranker (`app/ml/ranking/embedding_ranker.py`).

## Requirement, verified against Phases.md

Phases.md's exact text (§Phase 13, Build list):

> `ml/ranking_eval/` — a labelled relevance set of at least 50
> candidate/job pairs; Precision@5, Precision@10, Recall@K, NDCG;
> TF-IDF versus embeddings compared.

This states only a total-count floor (≥50 pairs). It does not require
each pair to use a different job, and nothing elsewhere in
`Phases.md`/`PRD.md` (F14.1) imposes a one-pair-per-job or
unique-job-per-pair rule. Multiple pairs sharing a job is in fact
necessary for Precision@5/Precision@10/NDCG to be meaningful metrics at
all — each is computed over a ranked list *within one job's candidate
pool*, so a job needs a reasonably sized candidate pool behind it, not
just one or two labelled candidates.

## Final structure: 3 jobs × 17 candidates = 51 pairs

`ranking_pairs_labelling_sheet.csv` — **51 rows**, exactly 17 per job:

| job_id | Title | Source |
|---|---|---|
| 1 | Backend Engineer | `backend/scripts/seed.py` — committed product seed job |
| 2 | Data Scientist | `backend/scripts/seed.py` — committed product seed job |
| 3 | Backend Software Engineer | `backend/tests/test_interview.py`'s `_make_job()` defaults + that test's title/required_skills/min_experience_years overrides — the third real job fixture in the repository, and the exact job already used for the prior, real Phase 8 F8.4 candidate verification (`docs/EVALUATION.md`'s Phase 8 section) |

All three are real, established fixtures already present in the
repository before this labelling package existed — none was invented
for this task.

## Deterministic candidate-selection rule (no model output used)

**Rule:** take the 42 real candidate ids from the fixture corpus
(`real_eval_set` + `regression_eval_set`), sorted ascending
(`candidate_id` 1–42 — the real, live-assigned database identifiers
from uploading every fixture resume through the actual production
pipeline, in filename order; an arbitrary but fixed and fully neutral
ordering, unrelated to relevance). Walk that list 1→42, then continue
wrapping around 1→9 to produce a 51-item sequence (42 unique + 9
repeats — the minimum possible repeats, since 3 × 17 = 51 exceeds the
42-candidate pool by exactly 9). Split that sequence into three
consecutive blocks of 17, assigned to job 1, job 2, job 3 in order:

- Job 1 gets candidates 1–17
- Job 2 gets candidates 18–34
- Job 3 gets candidates 35–42, then (wrapping around) candidates 1–9

**This selection did not use TF-IDF scores, embedding scores, any
ranker output, fit scores, model predictions, or any other relevance
estimate at any step.** The only inputs were: the fixed list of
candidate ids, ascending numeric order, and simple modular
arithmetic to fill 51 slots from a 42-item pool. It is fully
deterministic and reproducible from `source_data_snapshot.json` alone.

**Diversity achieved:** all 42 real candidates appear at least once
across the three jobs (full coverage of the fixture corpus) — the 9
unavoidable repeats (candidates 1–9) are the ones that happen to sit at
the start of the fixed ordering, not a chosen or scored subset. No
candidate was excluded and no candidate appears more than twice.

**Known, honestly-reported imbalance from this neutral rule:** because
`real_eval_set`'s 12 candidates were uploaded before
`regression_eval_set`'s 30 (giving them ids 1–12), and the wraparound
block (job 3's back half) reuses ids 1–9, the resulting source-set mix
is uneven — job 1: 12 `real_eval_set` + 5 `regression_eval_set`; job 2:
0 `real_eval_set` + 17 `regression_eval_set`; job 3: 9 `real_eval_set` +
8 `regression_eval_set`. This is a direct, undoctored consequence of
the neutral id-ordering rule, not a selection choice made to favor or
disfavor either source set — flagged here rather than smoothed over.

## Relevance scale

Every pair is judged on a **graded 0–3 scale**, per explicit
project-owner instruction (needed for NDCG to be meaningful — a binary
label would make NDCG degenerate toward Precision/Recall):

| Label | Meaning |
|---|---|
| 0 | Not relevant / would not shortlist |
| 1 | Weak relevance / poor fit |
| 2 | Good relevance / reasonable fit |
| 3 | Strong relevance / excellent fit |

`human_relevance_label` and `human_notes` are blank in every row of the
final sheet. No relevance judgment has been made or suggested.

## The original 84-pair pool — kept, but not the labelling sheet

`ranking_pairs_source_pool_84.csv` is the full cross product (all 42
candidates × jobs 1 and 2 only) built in the prior preparation pass. It
is preserved for auditability (e.g. if more labelled pairs are wanted
later, or to sanity-check the 51-row selection against a larger real
pool) but **is not the file to label** — the 51-row
`ranking_pairs_labelling_sheet.csv` above is. The 84-row pool predates
job 3 being added to the labelling scope, which is also why it only
covers jobs 1 and 2.

## How the candidate/job data was produced

Real, not fabricated: a scratch SQLite database (outside the
repository, in a session's temp scratchpad — never `backend/hiring.db`,
which was untouched throughout, verified by its unchanged mtime across
both preparation sessions) was migrated with `alembic upgrade head`,
seeded via the real `backend/scripts/seed.py`, and all 42 real resume
files were uploaded through the actual production endpoint
(`POST /jobs/{id}/resumes`) against a locally running instance of the
real FastAPI app. Job 3 was created through the real `POST /jobs`
endpoint with the exact field values `test_interview.py`'s fixture
specifies. `candidate_id`/`job_id` in the sheet are the real,
live-assigned database identifiers from that run.
`source_data_snapshot.json` holds the full raw fetch
(`GET /candidates/{id}`, `GET /jobs/{id}`) both sheets are built from.

## Limitations / things worth knowing before labelling

- **`candidate_experience_years` comes from the live pipeline's current
  extraction, not from `real_eval_set/labels.json`'s hand-verified gold
  values**, and the two do not always agree — e.g. `resume_001.pdf`
  (Aaron Whitfield, row R001) shows 6.6 years live vs. 7.5 hand-verified
  in the label file. See `Memory.md`'s Phase 13 Known Issues entry for
  this specific case — it is recorded there as an open finding to
  investigate during the two-column PDF work, not yet diagnosed. Prefer
  the linked source resume file over this column when it looks off.
- These are invented-person, real-format fixture resumes (Rules.md §7),
  not real personal data.
