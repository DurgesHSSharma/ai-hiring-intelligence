# AI Hiring Intelligence

An AI-assisted recruiting platform for resume screening, candidate ranking, skill-gap analysis, interview-question generation, and employee attrition prediction.

## What it does

Recruiters create a job, batch-upload candidate resumes, and get back a ranked, explainable fit score for each candidate — never a bare number, always the full breakdown. From there they can inspect a candidate's skill gaps, generate resume-grounded interview questions, and separately check an employee's predicted attrition risk. Aggregate analytics summarize scores, skills, and attrition across the system.

## Core capabilities

- **Resume ingestion** — batch upload of PDF/DOCX resumes, with per-file text extraction, field extraction (name, contact info, education, experience), and dictionary-based skill matching. A parse failure on one file never fails the batch.
- **Candidate ranking / scoring** — a weighted composite fit score (resume match, skill match, experience, education), computed via TF-IDF or sentence-embedding similarity depending on configuration. Every score response includes its full sub-score breakdown.
- **Skill-gap analysis** — matched vs. missing required/preferred skills per candidate/job pair, against a 423-entry skill dictionary.
- **Interview-question generation** — an LLM generates categorized interview questions grounded in a candidate's actual resume content, with an automated filter that rejects ungrounded output rather than padding the count.
- **Attrition prediction** — a calibrated probability, a three-tier risk level, and the top contributing factors for a submitted employee profile. Never phrased as a statement about a person's intention.
- **Analytics** — aggregate views across scoring, skill coverage, and attrition risk.

## Architecture / technology stack

**Backend:** FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2, PostgreSQL 16 (SQLite by default for local development)

**ML / NLP:** spaCy, sentence-transformers, scikit-learn, imbalanced-learn (SMOTE), pdfplumber, python-docx

**LLM:** OpenAI-compatible client (default configuration targets Groq) or Anthropic, behind a single provider-agnostic interface

**Frontend ("HireIntel"):** React 19, Vite, TypeScript, Tailwind CSS v4, TanStack Query, React Router v7, Recharts

**Infrastructure:** Docker, Docker Compose (backend + PostgreSQL + a migration service), GitHub Actions CI

See [Architecture.md](Architecture.md) for the full layering, data model, and API contract.

## End-to-end workflow

1. A recruiter creates a job with required skills, seniority, and experience requirements.
2. Resumes are batch-uploaded (PDF/DOCX), parsed, and field/skill-extracted automatically.
3. Candidates are scored against the job — a composite fit score with a full resume/skill/experience/education breakdown.
4. The recruiter reviews a candidate's skill gaps and generates grounded interview questions.
5. Separately, an employee profile can be submitted for attrition risk assessment (see Limitations — this population is not connected to candidates today).
6. Aggregate analytics summarize scoring, skill coverage, and attrition across the system.

## Screenshots / demo

No screenshots are included yet — none have been captured as of this document. Run the application locally or via Docker Compose (see Setup) to see it live.

## Measured ML results

Every figure below was produced by a rerunnable script or a recorded, committed evaluation sheet — see `docs/EVALUATION.md` for full methodology, per-metric interpretation, and source scripts. Nothing here is estimated or rounded favorably.

### Field extraction (name, email, phone, education, experience)

Measured against `real_eval_set` (n=12 real resumes), current extraction code plus corrected labels — this supersedes the older Phase 5/6 measurements in `docs/EVALUATION.md`, which were taken before a section-boundary bug fix and a label-arithmetic correction:

| Field | Result |
|---|---|
| Name | 11/12 (91.7%) |
| Email | 12/12 (100%) |
| Phone | 12/12 (100%) |
| Education level | 11/12 (91.7%) |
| Experience years | 12/12 (100%) |

### Skill extraction (dictionary matcher, precision/recall/F1)

Measured against 30 resumes with an independently human-labelled gold-skill list (89 total gold skills):

- **Precision: 0.900, Recall: 0.809, F1: 0.852**
- All 17 false negatives are vocabulary-coverage gaps (no dictionary entry exists) — zero are matcher failures on a skill the dictionary actually knows about.

### Candidate ranking (TF-IDF vs. embedding)

Measured against 51 labelled candidate/job pairs (3 real jobs × 17 candidates each), human relevance grades 0–3:

| Method | NDCG (overall) |
|---|---|
| TF-IDF | 0.854 |
| Embedding | 0.847 |

**The near-equal overall average conceals opposite-direction failure modes and should not be read as "the methods agree."** Embedding wins decisively on one job (0.950 vs. 0.718), TF-IDF wins decisively on another (0.890 vs. 0.615). TF-IDF has a demonstrated hard-zero tie-breaking problem; embedding has a demonstrated baseline-similarity inversion that ranked one genuinely strong candidate below several irrelevant ones.

### Semantic skill-match threshold — validated, and disabled by design

A separate, optional "semantic" skill-matching fallback (embedding similarity between a required skill and a candidate's stated skills) was measured against 20 human-labelled pairs. Best achievable accuracy across every possible threshold is **75%**, not a floor to tune upward from — the underlying signal measures topical closeness, not skill equivalence (e.g., `PostgreSQL`↔`MySQL` scores *higher* than the production threshold despite being different products). The feature ships **disabled** (`THRESHOLD_VALIDATED = False`) regardless of configuration.

### Score bands — a known, live calibration defect

Under the shipped default (`SCORING_METHOD=tfidf`), the same 51-pair evaluation set shows **all 51/51** candidates landing in the `weak_match` band regardless of actual relevance grade — the band field currently carries no discriminating information in that mode. Embedding mode reaches `moderate_match` for only 5 of 51. This is documented as a live defect, not a cosmetic gap; thresholds have not been changed pending a larger, more diverse evaluation set.

### Attrition prediction — shipped calibrated model

**Model:** Logistic Regression + SMOTE, sigmoid-calibrated (`CalibratedClassifierCV`). **This is the calibrated model actually served in production, at decision threshold 0.2005 — not the uncalibrated model's threshold-0.550 numbers**, which appear nearby in `docs/EVALUATION.md` and are easy to confuse with these (0.369 vs. 0.373 precision, 0.473 vs. 0.477 F1). Sealed test set (294 rows, 47 positive), opened once after every modeling decision was fixed from training/out-of-fold evidence:

| Metric | Value |
|---|---|
| Precision | 0.373 |
| Recall | 0.660 (31/47) |
| F1 | 0.477 |
| Brier score | 0.1030 |
| ROC-AUC | 0.7883 |

Risk tiers (Low / Medium / High) are a frozen, ranking-derived cut over the calibrated probability distribution, not fixed absolute-probability bands: High ≥ 0.3671, Medium ≥ 0.2270. Protected attributes (gender, marital status) are excluded from the feature set entirely.

### LLM interview-question quality

15 real, LLM-generated questions were rated 1–5 on relevance, specificity, technical quality, and resume grounding. Overall mean 4.22/5 across all four dimensions; relevance drops to 2.29/5 for a deliberately profession-mismatched test candidate (the expected, correct signal — grounded, specific questions can still be the wrong questions for the role). **These ratings are AI-assisted, entered at the project owner's explicit direction — not the independent human rating pass the product requirements specify.** That pass remains outstanding.

## Engineering / test results

- **Backend test suite: 532 passed, 2 xfailed** (measured directly against the current codebase).
- **Test coverage:** 97% across the whole backend application code, 95% for `services/`+`ml/` specifically, 100% for the API route layer.
- **ML artifact reproducibility:** the shipped attrition model artifacts were regenerated from scratch (the full three-script training/calibration/risk-tier pipeline) and compared byte-for-byte against the currently shipped artifacts — identical, confirming full determinism (`random_state=42` throughout).
- **Docker / CI:** a GitHub Actions workflow on a clean Ubuntu runner builds the backend image, starts PostgreSQL 16, runs a real `alembic upgrade head` migration against it (verified by querying for real tables afterward), starts the backend, confirms `/health` reports a live database connection, confirms `imbalanced-learn` imports inside the running container, and exercises a real authenticated `POST /attrition/predict` request that correctly returns `503`/`ATTRITION_MODEL_MISSING` on a fresh checkout with no model artifact present. This workflow is the authoritative Docker verification for this project — see Limitations.

## Setup

Full instructions — prerequisites, backend, attrition model artifacts, frontend, and a Docker Compose alternative — are in **[docs/SETUP.md](docs/SETUP.md)**. In short: `pip install -r backend/requirements.txt`, copy `.env.example` to `.env`, `alembic upgrade head`, `uvicorn app.main:app`; or `docker compose up` from the repository root.

## API documentation

Full endpoint reference, request/response shapes, and the standard error envelope are in **[docs/API.md](docs/API.md)**. Base path `/api/v1`; every non-2xx response uses the same `{"error": {"code", "message", "details"}}` shape.

## Security

- Password hashing via bcrypt; JWT bearer tokens for authentication.
- CORS restricted to a single configured origin — no wildcard.
- File uploads validated in four stages (extension, declared MIME type, magic bytes, size) before anything is parsed or stored.
- A per-user rate limit on the one endpoint that spends an LLM call (interview-question generation).
- No secrets committed to the repository — `.env` is gitignored, `.env.example` carries only empty placeholders; the Docker image runs as a non-root user and never bakes in a `.env` file.

## Limitations / known gaps

- **No container has ever loaded the real calibrated attrition model artifact.** CI verifies that `imbalanced-learn` imports successfully inside the container and, separately, that the API correctly returns `503`/`ATTRITION_MODEL_MISSING` when no model artifact is present — it has never verified an actual model load, because the model artifact (gitignored) is never present in that environment.
- **No production deployment exists.** The backend, database, and frontend have not been deployed anywhere; only local and CI environments have been exercised.
- **Local Docker verification has never succeeded on this project's own development machine** (a Windows-specific Docker Desktop startup failure, closed as won't-fix); clean-Linux GitHub Actions CI is the only Docker environment that has ever actually run this project's containers.
- **Semantic skill matching is measured and disabled**, not merely unbuilt — no threshold cleanly separates real synonyms from unrelated terms.
- **Score bands are uninformative under the default scoring method** — see Measured ML results above.
- **The LLM interview-question rating pass is AI-assisted, not the independent human rating the product specifies.** That pass has not been performed.
- **Attrition employee records are not connected to candidates or jobs anywhere in the data model.** There is currently no way to view a specific candidate's or applicant pool's attrition risk.
- **Dictionary-based skill extraction misses any skill with no entry in the skill dictionary** — 17 of 17 measured false negatives were vocabulary-coverage gaps, not matcher errors.
- **A model trained on one company's employee data does not transfer cleanly to another company or role mix.**

## Ethics / responsible use

- **Hiring decisions must not be automated solely from this system's output.** Every score, ranking, and prediction is a decision-support signal for a human recruiter, not a decision.
- **Human review is required** before any candidate is advanced, rejected, or contacted — the system itself never auto-rejects, auto-advances, or emails a candidate.
- **Attrition predictions are probabilistic estimates, not facts about a person.** A flagged employee is "worth a look," not someone predicted to leave; at the shipped operating threshold, roughly two of every three flagged employees will not actually leave (precision 0.373).
- **Model outputs should not be treated as definitive judgments about individuals.** Ranking quality varies by job and scoring method (see Measured ML results); a low score is not proof of poor fit, and a high attrition probability is not proof of intent.
- Protected attributes (gender, marital status) are never used as model features, scoring inputs, or filter options anywhere in the system.

## Privacy / PII disclosure

**Interview-question generation sends the candidate's full resume text, including their name, email address, and phone number where present, to the configured LLM provider** (an OpenAI-compatible endpoint or Anthropic, depending on configuration). This happens only when a recruiter explicitly requests question generation for a specific candidate — resume text is not sent to any LLM provider as part of upload, parsing, scoring, or any other operation.

## Project status

This project defines 17 phases (Phase 0 through Phase 16). **16 of 17 phases are complete. Phase 16 — Docker, deployment, and this README — is partially complete, not finished:**

- Backend Dockerfile, Docker Compose (backend + PostgreSQL + migrations), and CI verification — **done**.
- `docs/SETUP.md` — **done**, verified against a fresh virtual environment and a fresh frontend install.
- This README — **done** as of this commit.
- **Deployment to a hosting provider — not done.** Phase 16's deployment acceptance criterion is unmet; nothing in this repository has been deployed anywhere.

Verified deployment-*readiness* (a container that builds, migrates, starts, and degrades correctly, proven on clean-Linux CI) is not the same claim as an actual production deployment, and this document does not conflate the two.
