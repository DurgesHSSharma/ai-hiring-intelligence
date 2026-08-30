# Phases — AI Hiring Intelligence Platform

**Version:** 1.0
**Rule:** one phase at a time. A phase ends when every acceptance criterion is verified by running the code, not by reading it.

At the end of each phase, update `Memory.md` with: phase completed, what was built, decisions made, deviations, known issues, next phase.

---

## Phase map

```text
 0  Scaffolding                    ──┐
 1  FastAPI skeleton                 │  foundation
 2  Database + auth                 ─┘
 3  Jobs and candidates CRUD        ──┐
 4  Resume upload and extraction      │  core pipeline
 5  Field and skill extraction        │
 6  TF-IDF ranking + fit score        │
 7  Embedding upgrade               ──┘   ◄── MVP complete here
 8  LLM interview questions          ──┐
 9  Attrition data and EDA            │  intelligence layer
10  Attrition training                │
11  Attrition serving                ─┘
12  Analytics, compare, filter, export
13  Evaluation
14  Frontend integration
15  Testing and security hardening
16  Docker, deployment, README
```

The MVP boundary is the end of Phase 7. If everything after that stalls, the product still works end to end.

---

## Phase 0 — Scaffolding

**Goal:** an empty but correct project skeleton.

**Build**

- Directory tree exactly as `Architecture.md` §3, excluding `frontend/`.
- `.gitignore` covering `.env`, `__pycache__/`, `*.db`, `backend/storage/`, `data/raw/`, `data/processed/`, `ml/artifacts/*.joblib`, `.venv/`, `node_modules/`, `.ipynb_checkpoints/`.
- `.env.example` with every key from `Architecture.md` §8, all values empty.
- `backend/requirements.txt` and `ml/requirements.txt`, pinned, only approved packages.
- `data/README.md` placeholder.
- `Memory.md` created with the initial template.

**Acceptance**

- `pip install -r backend/requirements.txt` completes in a clean virtual environment.
- `python -c "import fastapi, sqlalchemy, pdfplumber, sklearn"` runs without error.
- No `.env` exists in the tree.

**Do not** write application logic, models, or routes.

**Note (added in the Phase 8 timeframe):** `.env.example` from the build list above was never actually created. It stayed missing through every phase since — `.env` is gitignored, so every session ran against a local `.env` that already worked, and Phase 0's own acceptance criteria never re-checked for the file's presence. Caught during a doc-drift review and created then, built from `config.py`'s `Settings` class directly rather than reconstructed from memory of this phase. See Memory.md.

---

## Phase 1 — FastAPI skeleton

**Goal:** a server that starts, answers, logs, and fails predictably.

**Build**

- `config.py` using pydantic-settings, validated at import. Weight sum check, `SCORING_METHOD` allowed-values check.
- `core/logging.py` — structured logger, no `print` anywhere.
- `core/exceptions.py` — the full `AppError` hierarchy from `Rules.md` §5.2.
- `core/error_handlers.py` — maps `AppError`, `RequestValidationError`, and unhandled exceptions to the error envelope. Correlation id on 500s.
- `main.py` — app factory, CORS middleware from config, router mount at `/api/v1`, lifespan handler stub.
- `api/health.py` — `GET /health`.

**Acceptance**

- `uvicorn app.main:app --reload` starts clean.
- `GET /api/v1/health` returns `{"status": "healthy", ...}`.
- `/docs` renders.
- A deliberately raised `NotFoundError` returns the exact envelope shape with a 404.
- An unhandled exception returns `INTERNAL_ERROR` with a correlation id and no traceback in the body, while the full traceback appears in the server log.
- Removing a required key from `.env` makes startup fail with a readable message.

**Do not** add database code or business endpoints.

---

## Phase 2 — Database and authentication

**Goal:** persistence and a login that works.

**Build**

- `database.py` — engine, `SessionLocal`, `Base`, `get_db` dependency.
- All SQLAlchemy models from `Architecture.md` §5.2, with indexes, unique constraints, and `ondelete` behaviour.
- Alembic initialised; first migration creates every table.
- `core/security.py` — bcrypt hash and verify, JWT encode and decode.
- `services/auth_service.py`, `schemas/auth.py`, `api/auth.py` — register, login, me.
- `dependencies.py` — `get_current_user`, pagination params.
- Auth applied to every router except health and auth.
- Tests: register, duplicate email conflict, login success, wrong password, protected route without token, expired token.

**Acceptance**

- `alembic upgrade head` creates the schema on a fresh SQLite file.
- Register returns 201 and no `password_hash` field anywhere in the response.
- Duplicate email returns 409 with `DUPLICATE_EMAIL`.
- Login returns a token that works on `/auth/me`.
- A protected route without a token returns 401 `TOKEN_EXPIRED` or `INVALID_CREDENTIALS` as appropriate.
- All Phase 2 tests pass.

**Do not** build password reset, email verification, or refresh tokens.

---

## Phase 3 — Jobs and candidates CRUD

**Goal:** the resource layer, with no AI anywhere in it.

**Build**

- `job_service.py` and `api/jobs.py` — list with search, status filter and pagination; create; detail with aggregate fields; patch with stale-marking; delete with correct cascade.
- `candidate_service.py` and `api/candidates.py` — list with pagination, detail, delete.
- `PATCH /applications/{id}` for status changes.
- `schemas/common.py` — `Page[T]` generic, shared enums.
- Seed script creating one user and two sample jobs for local work.
- Tests for each endpoint, success and failure.

**Acceptance**

- Full CRUD works through `/docs`.
- Pagination returns the correct `total` and `pages` on 50 seeded jobs.
- Editing a job description sets `is_stale = true` on its existing scores (verifiable once scores exist; assert the service path with a fabricated score row).
- Deleting a job removes its applications and scores and leaves candidate rows intact.
- 404s return `JOB_NOT_FOUND` / `CANDIDATE_NOT_FOUND`.

**Do not** touch resume parsing or scoring.

---

## Phase 4 — Resume upload and text extraction

**Goal:** a file becomes clean, correct text in the database.

**Build**

- `utils/files.py` — extension, MIME, magic-byte, and size validation; UUID storage naming.
- `ml/extraction/text_extractor.py` — pdfplumber and python-docx paths behind one interface.
- `ml/extraction/text_cleaner.py` — whitespace normalisation, header and footer stripping, hyphen-break repair, section order preserved.
- `resume_service.py` — the batch orchestration from `Architecture.md` §7.1, committing per file.
- `POST /jobs/{job_id}/resumes` and `GET /candidates/{id}/resume-file`.
- Test fixtures: at least one PDF, one DOCX, one corrupt file, one oversized file, one image-only PDF.

**Acceptance**

- Uploading 10 mixed files creates 10 candidates with non-empty `resume_text`.
- A corrupt file returns `status: parse_failed` in its result entry while the other nine succeed.
- An image-only PDF is recorded as `parse_failed` with `RESUME_TEXT_TOO_SHORT`, not as an empty candidate.
- A `.txt` upload is rejected file-level with `UNSUPPORTED_FILE_TYPE`, and an oversized upload is rejected file-level with `FILE_TOO_LARGE` — both embedded in that file's `results` entry, not a top-level HTTP status. The batch endpoint always returns 200 once the job exists, the file list is non-empty, and the batch is within `MAX_FILES_PER_BATCH`; only those three request-level conditions produce a top-level error (404, 400 `NO_FILES_PROVIDED`, 400 `BATCH_LIMIT_EXCEEDED`). Amended from the original single-file-endpoint wording — see Memory.md.
- Extracted text for a known fixture is manually verified as readable and correctly ordered.
- The stored file streams back with the right content type.

**Do not** extract fields or skills yet. This phase only proves text extraction is trustworthy.

---

## Phase 5 — Field and skill extraction

**Goal:** structured candidate data.

**Build**

- `ml/extraction/field_extractor.py` — email and phone by regex; name by first-lines heuristic with spaCy `PERSON` fallback; education by degree patterns against `data/education.json`; experience years from date ranges with an NER fallback; projects and certifications by section headings.
- `data/skills.json` — minimum 250 canonical skills with aliases and type tags.
- `ml/skills/skill_matcher.py` — word-boundary-safe, case-insensitive, alias-resolving matching. Must not match `R` inside `React` or `Go` inside `Google`.
- Job-side skill extraction so the recruiter need not list every skill manually.
- Wire both into the upload pipeline; populate `candidate_skills`.
- Email-based dedupe: existing candidate is updated and linked to the new job.

**Acceptance**

- On a labelled set of 30 real-format resumes, measured extraction rates are recorded in `docs/EVALUATION.md` — the actual numbers, whatever they are.
- The word-boundary cases above are covered by unit tests and pass.
- Uploading the same resume twice produces one candidate and two applications.
- `GET /candidates/{id}` returns skills grouped by type.

**Do not** add semantic skill matching yet — that arrives with embeddings in Phase 7.

---

## Phase 6 — TF-IDF ranking and fit score

**Goal:** the first working ranked shortlist. This is the moment the product becomes real.

**Build**

- `ml/ranking/base.py` — the `Ranker` protocol.
- `ml/ranking/tfidf_ranker.py` — vectorise, cosine similarity, scale to 0–100.
- `ml/ranking/factory.py` — returns a ranker from config.
- `ml/skills/skill_gap.py` — matched, missing, additional, percentage.
- `scoring_service.py` — experience sub-score, education sub-score, weighted composition, band assignment, upsert with method and version.
- `POST /jobs/{id}/score`, `GET /jobs/{id}/rankings`, `GET /candidates/{id}/score`, `GET /candidates/{id}/skill-gap`.
- Unit tests including the worked example: 85/90/80/100 → 87.5.

**Acceptance**

- Scoring 50 candidates against one job finishes in under 60 seconds.
- The ranked list is ordered by `final_fit_score` descending and the ordering is sensible on manual inspection of the top and bottom three.
- Every score response carries all four sub-scores plus the band.
- A candidate with no extracted text is skipped with a reason, not scored zero.
- A job with no required skills returns `JOB_HAS_NO_SKILLS`.
- Changing a weight in `.env` changes the results; weights not summing to 1.0 block startup.

**MVP milestone.** Upload → parse → extract → rank works end to end.

---

## Phase 7 — Embedding upgrade

**Goal:** semantic matching, without losing TF-IDF.

**Build**

- `ml/ranking/embedding_ranker.py` — `all-MiniLM-L6-v2` as a lazy singleton loaded once.
- Candidate embedding cached on the candidate row, computed on first use.
- Job embedding computed once per batch scoring run.
- Semantic fallback in skill matching: a required skill above the similarity threshold counts as a partial match, tagged `source: semantic`.
- Config switch between `tfidf` and `embedding`, with both fully working.

**Acceptance**

- The model loads once at startup or first use, never per request.
- Scoring 50 candidates in embedding mode finishes in under 90 seconds.
- Re-scoring the same candidates for a second job reuses cached embeddings and is measurably faster.
- Ranking differences between TF-IDF and embedding mode are compared on the same job and the observation is recorded in `Memory.md`.
- Partial skill matches are visibly distinct from exact matches in the API response.
- A missing or unloadable model returns `EMBEDDING_MODEL_UNAVAILABLE` and TF-IDF still works.

---

## Phase 8 — LLM interview questions

**Goal:** questions a recruiter could actually use, grounded in the specific resume.

**Build**

- `ml/llm/client.py` — provider-agnostic wrapper, explicit timeout, one retry on transient failure.
- `ml/llm/prompts.py` — the question-generation template as a named constant.
- `ml/llm/parser.py` — strict JSON parse plus Pydantic validation, one repair retry.
- `interview_service.py` — build context from job, skills, experience, projects, missing skills; call; validate; grounding filter; persist with a `generation_batch` uuid.
- `POST` and `GET /candidates/{id}/interview-questions`.
- Tests with the client mocked: valid response, malformed JSON, timeout, ungrounded question filtered out.

Provider selection now covers any OpenAI-compatible endpoint, not only
OpenAI itself, via `OPENAI_BASE_URL`. The shipped configuration targets
Groq.

**Acceptance**

- Generation returns 5–8 grounded questions when enough of the model's output survives the filter. The response always carries `requested`/`generated`/`grounded` counts and a `partial` flag (`grounded < 5`) — a caller distinguishes a full result from a resume that only yielded a few groundable questions from the response body itself, never from array length alone. Between 1 and 4 survivors return 200 with the shorter list (`partial: true`), logged at WARNING. Zero survivors returns 503 `INSUFFICIENT_GROUNDED_QUESTIONS`, distinct from `LLM_INVALID_OUTPUT` (reserved for output that fails JSON/schema validation). Every returned question still carries a category and a difficulty.
- Reading two generated sets side by side, a person can tell which resume produced which — the questions name real projects, technologies, or claims.
- A second `GET` returns stored questions without an API call; `regenerate: true` replaces the set.
- With the provider key removed, the endpoint returns 503 `LLM_UNAVAILABLE` and every other endpoint continues to work.
- Malformed model output never reaches the database.
- No API key appears in any log line.

---

## Phase 9 — Attrition data and EDA

**Goal:** understand the data before modelling it. Offline work in `ml/` only.

**Build**

- Obtain a public HR attrition dataset into `data/raw/`. Record source, licence, and download steps in `data/README.md`.
- `ml/attrition/01_eda.ipynb` — missing values, duplicates, dtypes, outliers, class balance.
- Attrition rate broken down by salary band, department, overtime, job satisfaction, tenure, and time since last promotion, with charts.
- `ml/attrition/02_preprocessing.py` — a reusable, serialisable preprocessing pipeline.
- Explicit exclusion of gender, marital status, and any other protected attribute, documented in the notebook.

**Acceptance**

- The notebook runs top to bottom on a clean kernel.
- Class balance is stated as a real ratio.
- At least six labelled visualisations exist.
- The final feature list is written down and matches the `employees` table.
- The preprocessing pipeline serialises and reloads with identical output.

**Do not** train a model in this phase.

---

## Phase 10 — Attrition model training

**Goal:** a chosen, justified, serialised model.

**Build**

- `ml/attrition/03_train.py` — Logistic Regression, Random Forest, and XGBoost on identical splits, `random_state=42`.
- Imbalance handling: `class_weight="balanced"` and one resampling approach, results compared before and after.
- `ml/attrition/04_evaluate.py` — accuracy, precision, recall, F1, ROC-AUC, confusion matrix on a held-out test set.
- Feature importances; SHAP only if it does not push inference past 500 ms.
- Artefacts saved together: model, preprocessor, `feature_names.json`, `metrics.json` with a version string.
- `performance_rating` has only 2 distinct values in this dataset. Check its feature importance is not misleading before surfacing it as a contributing factor.

**Acceptance**

- All three models trained and compared in one table of real numbers.
- The chosen model is justified on recall and precision, not accuracy alone, and the justification is recorded.
- Before/after imbalance-handling results are both reported.
- Artefacts load in a fresh process and reproduce the recorded test metrics exactly.
- `docs/EVALUATION.md` contains the measured numbers.

---

## Phase 11 — Attrition serving

**Goal:** the model reachable over the API with an explanation attached.

**Build**

- `ml/attrition/predictor.py` — artefact loading, `predict_proba`, importance extraction.
- `ml/attrition/features.py` — dict to ordered vector, raising `INVALID_FEATURE_SET` naming missing keys.
- Lifespan loading; a missing artefact disables only the attrition routes.
- `attrition_service.py`, `POST /attrition/predict`, `POST /attrition/predict/batch`, `GET /attrition/employees`, `GET /attrition/model-info`.
- Risk banding and prediction persistence.

**Acceptance**

- Single prediction returns in under 500 ms with probability, risk band, and top factors.
- Batch of 100 records works in one call.
- A missing feature returns 400 naming exactly which field is missing.
- Deleting the artefact file makes attrition routes return 503 `ATTRITION_MODEL_MISSING` while every other endpoint stays healthy.
- `model-info` reports the model type, version, test metrics, and feature list.
- Predictions match the offline model's output for the same input.

---

## Phase 12 — Analytics, comparison, filtering, export

**Goal:** the features that make it feel like a product rather than a pipeline.

**Build**

- `analytics_service.py` and four endpoints: overview funnel, skills, scores, attrition — all with `job_id` and date-range filters.
- Comparison: `GET /jobs/{id}/compare?candidate_ids=`, 2–4 candidates, full matrix, best-per-row marked.
- Full filter, search, and sort set on `/candidates`, all executed in SQL.
- `export_service.py` — CSV honouring the active filters. PDF shortlist optional and last.

**Acceptance**

- Every analytics number is verifiable against a manual database query.
- Analytics respond in under 1.5 s with 500 candidates seeded.
- Combined filters behave as AND: `min_score=80 AND skills=Python AND min_experience=2` returns only rows satisfying all three.
- Sorting is stable and correct in both directions.
- Comparing four candidates returns every field in the matrix.
- CSV opens cleanly in a spreadsheet and its rows match the filtered API result exactly.
- No endpoint loads a full table into Python to filter it.

---

## Phase 13 — Evaluation

**Goal:** real numbers for every AI component. No estimates.

**Build**

- `ml/ranking_eval/` — a labelled relevance set of at least 50 candidate/job pairs; Precision@5, Precision@10, Recall@K, NDCG; TF-IDF versus embeddings compared.
- `ml/skill_eval/` — hand-labelled skill lists for at least 30 resumes; precision, recall, F1.
- `ml/llm_eval/` — 20 generated questions rated 1–5 by a human on relevance, specificity, technical quality, and resume grounding. This human rating is the actual measure of question quality — Phase 8's automated grounding filter (substring matching against candidate-derived anchors) is a floor that rejects the most generic outputs, not a substitute for it. See `docs/EVALUATION.md`'s Phase 8 section.
- `docs/EVALUATION.md` — methodology, set sizes, and results for all four, including the attrition numbers from Phase 10.
- Revisit two-column PDF extraction against the labelled corpus. See Memory.md known limitations.
- The semantic skill-match threshold (currently 0.5) must be **validated** against `ml/skill_eval`'s labelled set before the feature is enabled in any real use — not merely tuned. A real-model sanity check in Phase 7 found it inverted on the cases that matter (a different product passes, a genuine paraphrase fails); see `docs/EVALUATION.md`'s Phase 7 section, recorded there as a blocking issue. `SEMANTIC_SKILL_MATCHING` refuses to run regardless of its config value until this validation happens and `app/ml/skills/skill_gap.py`'s `THRESHOLD_VALIDATED` is flipped to `True`.
- Calibrate score band thresholds (F7.5) against the labelled ranking set, per scoring method. Current thresholds are uncalibrated and produce different bands for identical inputs across methods.
- The Phase 8 side-by-side comparison has been run twice, for real, against the same two `real_eval_set` candidates and job. First run (pre-fix): raw question quality and distinguishability were confirmed — read blind, a reader can tell the two sets apart within one question — but the production endpoint returned 503 on 7 of 7 real attempts, because the grounding filter rejected most of both real sets (including the most specific, best questions in each), since both candidates' empty `projects`/`certifications` left the filter with only bare skill names as anchors. **Fixed**: the grounding filter now also draws anchors from Experience-section resume text (single-token acronyms/metrics plus multi-word proper-noun runs on date-bearing lines — see `interview_service.py`'s `_experience_section_anchors()`), and `_is_grounded()` is word-boundary-safe. Re-run after the fix: Aaron Whitfield 10/10 generated questions grounded, Wei Chen 8/10 — both comfortably in the full-success band, 0 of 2 candidates need the new partial-result path. Full transcript in `docs/EVALUATION.md`'s Phase 8 section. The formal `ml/llm_eval/` human 1-5 rating study can now run against an ordinary real resume; it has not been run yet.

**Acceptance**

- Every number in `docs/EVALUATION.md` was produced by a script that can be re-run, or by a recorded human rating sheet.
- Evaluation set sizes are stated alongside every metric.
- Weak results are reported as they are, with a note on why. Nothing is rounded upward or presented selectively.

---

## Phase 14 — Frontend integration

**Goal:** the owner's frontend talking to this backend, with no frontend file modified.

**Precondition:** the frontend has been delivered by the owner.

**Build**

- Read the frontend's API service layer, type definitions, and page components.
- Produce a diff table: expected endpoint, method, request shape, response shape versus what the backend exposes.
- Change the backend to match — field names, casing, nesting, status codes, enum values.
- Add the frontend dev origin to `CORS_ORIGINS`.
- Walk every page against the live API and fix backend-side gaps.

**Acceptance**

- Login, job creation, resume upload, ranking, candidate detail, question generation, attrition, analytics, comparison, and export all work from the running frontend.
- No file inside `frontend/` was created, edited, or deleted.
- Any mismatch that cannot be resolved backend-side is reported in writing with a proposed frontend change for the owner to make.
- `docs/API.md` reflects the final contract.

---

## Phase 15 — Testing and security hardening

**Goal:** ready to be deployed without embarrassment.

**Build**

- Fill coverage gaps: every endpoint success and failure, every scoring formula, extraction edge cases, LLM failure paths, attrition validation.
- Security pass: password hashing verified, JWT expiry enforced, protected routes checked, upload validation confirmed at all four levels, CORS restricted to the configured list, no secret in any tracked file, no internals in any error body.
- Consider a per-user generation rate limit on the interview-question endpoint. None exists — see Memory.md known issues.
- Startup smoke test on a fresh database and a fresh virtual environment.

**Acceptance**

- The full suite passes from a clean checkout.
- Coverage on `services/` and `ml/` is measured and reported honestly.
- A scripted attempt to upload an executable renamed to `.pdf` is rejected at the magic-byte check.
- Grepping the tracked tree for key patterns finds nothing.
- Every 4xx and 5xx response conforms to the envelope.

---

## Phase 16 — Docker, deployment, README

**Goal:** someone else can run it.

**Build**

- `backend/Dockerfile` — slim base, layered dependency install, non-root user, no secrets baked in.
- `docker-compose.yml` — backend plus `postgres:16` with a named volume and a healthcheck.
- Migration path verified on PostgreSQL, not only SQLite.
- Deploy backend to Render or Railway, database to managed PostgreSQL, frontend to Vercel with production `CORS_ORIGINS` and API base URL set.
- `docs/SETUP.md` — local setup from scratch.
- `README.md` — written last, following the structure supplied separately by the owner, with real measured metrics, honest limitations, and the ethical considerations section.
- Document that question generation sends the candidate's full resume text, including any name, email, and phone it contains, to the configured LLM provider.

**Acceptance**

- `docker-compose up` gives a working stack from a clean clone plus a filled `.env`.
- `alembic upgrade head` runs clean against PostgreSQL.
- The deployed frontend reaches the deployed backend over HTTPS with no CORS errors.
- A person following `docs/SETUP.md` on a clean machine reaches a running server without asking a question.
- The README contains no unmeasured metric and no claim the code does not support.

---

## Working agreement

1. Announce the phase before starting it.
2. Build only that phase.
3. Run it. Test it.
4. Verify every acceptance criterion explicitly, one by one.
5. Update `Memory.md`.
6. Report what is done, what is not, and what is untested — then stop and wait.

Backlog items discovered mid-phase go into `Memory.md`. They do not get built on the spot.

Verify against real_eval_set alongside fixtures. Fixtures encode assumptions about document shape, and in Phases 4, 5 and 8 those assumptions were wrong in ways only real files exposed.
