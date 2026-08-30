# Architecture — AI Hiring Intelligence Platform

**Version:** 1.0
**Related docs:** `PRD.md`, `Rules.md`, `Phases.md`, `Design.md`

---

## 1. System overview

```text
                          ┌──────────────────────────┐
                          │        HR USER           │
                          └────────────┬─────────────┘
                                       │
                          ┌────────────▼─────────────┐
                          │   React + TypeScript     │
                          │   (owned separately)     │
                          └────────────┬─────────────┘
                                       │ REST / JSON / JWT
                          ┌────────────▼─────────────┐
                          │      FastAPI (api/)      │
                          │  routing · validation    │
                          │  auth · error envelope   │
                          └────────────┬─────────────┘
                                       │
                          ┌────────────▼─────────────┐
                          │    Service layer         │
                          │  all business logic      │
                          └───┬────────┬────────┬────┘
                              │        │        │
            ┌─────────────────▼──┐  ┌──▼─────┐  └──────────────┐
            │  Resume pipeline   │  │  LLM   │                 │
            │  extract · clean   │  │ client │                 │
            │  parse · skills    │  └────────┘                 │
            └─────────┬──────────┘                             │
                      │                              ┌─────────▼─────────┐
            ┌─────────▼──────────┐                   │  Attrition model  │
            │  Ranking engine    │                   │  loaded .joblib   │
            │  TF-IDF │ MiniLM   │                   └─────────┬─────────┘
            └─────────┬──────────┘                             │
                      │                                        │
                      └──────────────┬─────────────────────────┘
                                     │
                        ┌────────────▼─────────────┐
                        │  SQLAlchemy ORM          │
                        └────────────┬─────────────┘
                                     │
                        ┌────────────▼─────────────┐
                        │  SQLite (dev)            │
                        │  PostgreSQL (prod)       │
                        └──────────────────────────┘

        ml/  ── offline training ──►  ml/artifacts/*.joblib  ──► loaded by app/ml
```

Two things run outside the request path:

- **`ml/`** is offline. Notebooks and training scripts produce serialised artefacts. The API loads artefacts; it never trains.
- **Uploaded files** live on disk (dev) or object storage (prod). The database stores paths, not blobs.

---

## 2. Layering rules

Four layers, strictly one-directional. This is the single most important structural rule in the codebase.

```text
api/        HTTP only — routing, auth dependency, request/response schemas
   ↓        may call services. may NOT touch models or ML directly.
services/   business logic — orchestration, transactions, rules
   ↓        may call models, ml, utils. may NOT import from api.
models/     SQLAlchemy ORM — table definitions and relationships only
ml/         inference wrappers — pure functions over data, no DB access
```

Consequences:

- A route function contains no `if` statement about business rules and no query building. It calls one service function and returns the result.
- A service function never sees a `Request` object, never raises `HTTPException`, and never knows HTTP status codes. It raises domain exceptions from `core/exceptions.py`, which a global handler maps to HTTP.
- An ML module never opens a database session. It receives text or a feature dict and returns numbers or structures.
- A model file contains no logic beyond column definitions, relationships, and simple hybrid properties.

---

## 3. Folder structure

```text
ai-hiring-intelligence/
│
├── PRD.md
├── Architecture.md
├── Rules.md
├── Phases.md
├── Design.md
├── Memory.md                      # created at the start of Phase 1
├── README.md                      # written last, structure supplied separately
├── .gitignore
├── .env.example
├── docker-compose.yml
│
├── frontend/                      # OWNED SEPARATELY — never modified by the build
│   └── ...
│
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                # app factory, middleware, router mount, lifespan
│   │   ├── config.py              # pydantic-settings, reads .env, validated at import
│   │   ├── database.py            # engine, SessionLocal, Base, get_db
│   │   ├── dependencies.py        # get_current_user, pagination params, common deps
│   │   │
│   │   ├── core/
│   │   │   ├── security.py        # bcrypt hashing, JWT encode/decode
│   │   │   ├── exceptions.py      # AppError hierarchy
│   │   │   ├── error_handlers.py  # domain exception → JSON envelope
│   │   │   └── logging.py         # structured logger setup
│   │   │
│   │   ├── api/
│   │   │   ├── __init__.py        # api_router, includes every module below
│   │   │   ├── health.py
│   │   │   ├── auth.py
│   │   │   ├── jobs.py
│   │   │   ├── candidates.py
│   │   │   ├── resumes.py
│   │   │   ├── scoring.py
│   │   │   ├── interview.py
│   │   │   ├── attrition.py
│   │   │   ├── analytics.py
│   │   │   └── export.py
│   │   │
│   │   ├── models/                # SQLAlchemy
│   │   │   ├── __init__.py        # imports every model so Base sees them
│   │   │   ├── base.py            # TimestampMixin, common columns
│   │   │   ├── user.py
│   │   │   ├── job.py
│   │   │   ├── candidate.py
│   │   │   ├── application.py
│   │   │   ├── candidate_skill.py
│   │   │   ├── candidate_score.py
│   │   │   ├── interview_question.py
│   │   │   ├── employee.py
│   │   │   └── attrition_prediction.py
│   │   │
│   │   ├── schemas/               # Pydantic v2
│   │   │   ├── common.py          # Page[T], ErrorEnvelope, enums
│   │   │   ├── auth.py
│   │   │   ├── job.py
│   │   │   ├── candidate.py
│   │   │   ├── resume.py
│   │   │   ├── score.py
│   │   │   ├── interview.py
│   │   │   ├── attrition.py
│   │   │   └── analytics.py
│   │   │
│   │   ├── services/
│   │   │   ├── auth_service.py
│   │   │   ├── job_service.py
│   │   │   ├── candidate_service.py
│   │   │   ├── resume_service.py       # upload → parse → persist orchestration
│   │   │   ├── scoring_service.py      # fit score composition, batch rescoring
│   │   │   ├── interview_service.py    # prompt build, LLM call, validation, persist
│   │   │   ├── attrition_service.py
│   │   │   ├── analytics_service.py
│   │   │   └── export_service.py
│   │   │
│   │   ├── ml/                    # inference only — no DB, no HTTP
│   │   │   ├── extraction/
│   │   │   │   ├── text_extractor.py   # pdfplumber / python-docx → raw text
│   │   │   │   ├── text_cleaner.py     # normalisation
│   │   │   │   └── field_extractor.py  # name, email, phone, education, experience
│   │   │   ├── skills/
│   │   │   │   ├── skill_matcher.py    # dictionary + alias + boundary-safe matching
│   │   │   │   └── skill_gap.py        # matched / missing / additional
│   │   │   ├── ranking/
│   │   │   │   ├── base.py             # Ranker protocol: score(resume, jd) -> float
│   │   │   │   ├── tfidf_ranker.py
│   │   │   │   ├── embedding_ranker.py # sentence-transformers, lazy singleton
│   │   │   │   └── factory.py          # returns ranker per config
│   │   │   ├── attrition/
│   │   │   │   ├── predictor.py        # loads artefact, predict_proba, importances
│   │   │   │   └── features.py         # dict → ordered feature vector
│   │   │   └── llm/
│   │   │       ├── client.py           # provider-agnostic wrapper
│   │   │       ├── prompts.py          # prompt templates as constants
│   │   │       └── parser.py           # strict JSON parse + schema validation
│   │   │
│   │   ├── utils/
│   │   │   ├── files.py           # validation, UUID naming, safe storage
│   │   │   ├── text.py
│   │   │   └── pagination.py
│   │   │
│   │   └── data/
│   │       ├── skills.json        # canonical skills + aliases + type
│   │       └── education.json     # degree ladder for education scoring
│   │
│   ├── alembic/
│   │   ├── versions/
│   │   └── env.py
│   ├── alembic.ini
│   ├── tests/
│   │   ├── conftest.py            # test client, in-memory DB, fixtures
│   │   ├── test_auth.py
│   │   ├── test_jobs.py
│   │   ├── test_resumes.py
│   │   ├── test_scoring.py
│   │   ├── test_interview.py
│   │   ├── test_attrition.py
│   │   └── fixtures/              # sample PDF and DOCX resumes
│   ├── storage/                   # uploaded files (gitignored)
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
│
├── ml/                            # offline work — not imported by the API
│   ├── attrition/
│   │   ├── 01_eda.ipynb
│   │   ├── 02_preprocessing.py
│   │   ├── 03_train.py            # trains all three models, writes metrics.json
│   │   ├── 04_evaluate.py
│   │   └── artifacts/
│   │       ├── attrition_model.joblib
│   │       ├── preprocessor.joblib
│   │       ├── feature_names.json
│   │       └── metrics.json
│   ├── ranking_eval/
│   │   ├── labelled_set.csv       # manual relevance labels
│   │   └── evaluate_ranking.py    # Precision@K, Recall@K, NDCG
│   ├── skill_eval/
│   │   └── evaluate_skills.py     # precision, recall, F1
│   ├── llm_eval/
│   │   └── rating_sheet.csv       # human 1–5 ratings
│   └── requirements.txt
│
├── data/
│   ├── raw/                       # gitignored
│   ├── processed/                 # gitignored
│   ├── samples/                   # a few committed sample resumes
│   └── README.md                  # dataset source, licence, how to obtain
│
└── docs/
    ├── API.md                     # generated summary of the contract
    ├── EVALUATION.md              # measured metrics only
    └── SETUP.md
```

---

## 4. Technology stack

### Backend

| Concern | Choice | Note |
|---|---|---|
| Language | Python 3.11 | Pinned. 3.12 not used until every ML dependency confirms support. |
| Framework | FastAPI | Async-capable routes, automatic OpenAPI. |
| Validation | Pydantic v2 | Request, response, config, and LLM output schemas. |
| ORM | SQLAlchemy 2.0 | Modern typed declarative style. |
| Migrations | Alembic | Every schema change is a migration. |
| Server | Uvicorn | `--reload` in dev, workers in prod. |
| Auth | python-jose + passlib[bcrypt] | JWT HS256. |
| Config | pydantic-settings | Fails at startup on a missing required key. |

### AI / ML

| Concern | Choice | Note |
|---|---|---|
| Data | pandas, NumPy | Offline training and analytics aggregation. |
| Classical ML | scikit-learn | TF-IDF, Logistic Regression, Random Forest, metrics. |
| Boosting | XGBoost | Third attrition candidate model. |
| NLP | spaCy `en_core_web_sm` | NER fallback for name and experience extraction. |
| Embeddings | sentence-transformers `all-MiniLM-L6-v2` | ~90 MB, CPU-friendly, loaded once. |
| Explainability | scikit-learn feature importances, SHAP optional | SHAP only if it does not slow inference past target. |
| Serialisation | joblib | Model plus preprocessor plus feature order, always together. |

### Resume processing

| Concern | Choice |
|---|---|
| PDF | pdfplumber |
| DOCX | python-docx |
| Patterns | `re` |
| Entities | spaCy |

### LLM

Provider-agnostic client. Default provider OpenAI, Anthropic supported by config switch. The service layer never imports a vendor SDK directly — it calls `app/ml/llm/client.py`.

### Database

SQLite for development, PostgreSQL for production. Only portable SQL and portable column types are used, so the switch is a `DATABASE_URL` change plus a migration run.

### Frontend (reference only — owned separately)

React, TypeScript, Tailwind CSS, shadcn/ui, React Router, Axios, Recharts, Zustand. Listed here so the API contract is designed for it. No frontend code is produced by this build.

### Deployment

Frontend on Vercel. Backend on Render or Railway. Managed PostgreSQL. Docker Compose for local parity.

---

## 5. Data model

### 5.1 Entity relationships

```text
users
  └── (audit only, no ownership scoping in v1)

jobs 1 ──── N applications N ──── 1 candidates
                 │                     │
                 │                     ├── N candidate_skills
                 │                     └── N interview_questions
                 └── 1 candidate_scores (unique per job+candidate)

employees 1 ──── N attrition_predictions
```

`applications` is the join between a job and a candidate. It exists because one candidate can be considered for several jobs and needs a per-job status. Without it, status is unrepresentable.

### 5.2 Tables

**users**

| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| name | str(120) | |
| email | str(255) | unique, indexed |
| password_hash | str(255) | bcrypt, never serialised |
| role | enum | recruiter · manager · analyst · admin |
| created_at | datetime | |

**jobs**

| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| title | str(200) | indexed |
| description | text | |
| required_skills | JSON | list of canonical skill strings |
| min_experience_years | float | |
| education_requirement | str(80) | maps to `education.json` ladder |
| seniority | enum | junior · mid · senior · lead |
| location | str(120) | |
| status | enum | open · closed |
| created_by | FK users.id | |
| created_at, updated_at | datetime | |

**candidates**

| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| name | str(160) | nullable — extraction may fail |
| email | str(255) | indexed, used for dedupe |
| phone | str(40) | nullable |
| resume_path | str(500) | UUID filename on disk |
| resume_filename | str(255) | original name, display only |
| resume_text | text | cleaned text |
| education | str(200) | nullable |
| education_level | int | ordinal from the ladder |
| experience_years | float | nullable |
| projects | JSON | list of extracted project blurbs |
| certifications | JSON | list |
| embedding | JSON | cached MiniLM vector, nullable |
| parse_status | enum | parsed · partial · parse_failed |
| parse_error | str(500) | nullable |
| created_at | datetime | |

**applications**

| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| candidate_id | FK, indexed | |
| job_id | FK, indexed | |
| status | enum | new · shortlisted · interviewed · selected · rejected |
| created_at, updated_at | datetime | |

Unique constraint on `(candidate_id, job_id)`.

**candidate_skills**

| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| candidate_id | FK, indexed | |
| skill_name | str(80) | canonical form |
| skill_type | enum | technical · tool · soft · domain |
| source | enum | dictionary · semantic |

Unique constraint on `(candidate_id, skill_name)`.

**candidate_scores**

| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| candidate_id | FK, indexed | |
| job_id | FK, indexed | |
| resume_match_score | float | 0–100 |
| skill_match_score | float | 0–100 |
| experience_score | float | 0–100 |
| education_score | float | 0–100 |
| final_fit_score | float | 0–100, indexed for sorting |
| matched_skills | JSON | list |
| missing_skills | JSON | list |
| additional_skills | JSON | list |
| scoring_method | enum | tfidf · embedding |
| score_version | int | bumped when weights or method change |
| is_stale | bool | set when the job is edited |
| created_at | datetime | |

Unique constraint on `(candidate_id, job_id)`.

**interview_questions**

| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| candidate_id | FK, indexed | |
| job_id | FK, indexed | |
| question | text | |
| category | enum | technical · project · experience · skill_verification · behavioral |
| difficulty | enum | easy · medium · hard |
| rationale | str(400) | which resume detail prompted it, nullable |
| generation_batch | uuid | groups one generation run |
| created_at | datetime | |

**employees**

Mirrors the public attrition dataset columns actually used, minus excluded sensitive attributes. Locked at Phase 8 once the feature set is final.

| Column | Type |
|---|---|
| id | int PK |
| age | int |
| department | str(80) |
| job_level | int |
| monthly_income | float |
| years_at_company | int |
| years_since_last_promotion | int |
| years_with_curr_manager | int |
| total_working_years | int |
| job_satisfaction | int |
| environment_satisfaction | int |
| relationship_satisfaction | int |
| performance_rating | int |
| overtime | bool |
| business_travel | str(40) |
| distance_from_home | int |
| percent_salary_hike | float |
| stock_option_level | int |
| attrition | bool (nullable — label, historical rows only) |

**attrition_predictions**

| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| employee_id | FK, indexed | |
| probability | float | 0–1 |
| risk_level | enum | low · medium · high |
| top_factors | JSON | `[{feature, contribution}]` |
| model_version | str(40) | |
| prediction_date | datetime | |

---

## 6. API contract

Base path `/api/v1`. All responses JSON. All protected routes require `Authorization: Bearer <token>`.

### 6.1 Standard envelopes

Success — the resource, unwrapped:

```json
{ "id": 12, "title": "Machine Learning Engineer" }
```

Paginated list:

```json
{
  "items": [],
  "total": 137,
  "page": 1,
  "page_size": 20,
  "pages": 7
}
```

Error — always this shape, for every non-2xx:

```json
{
  "error": {
    "code": "RESUME_PARSE_FAILED",
    "message": "No readable text found in the uploaded file.",
    "details": { "filename": "resume_scan.pdf" }
  }
}
```

`code` is a stable machine-readable string. `message` is safe to display to a user. `details` is optional and never contains a stack trace or SQL.

### 6.2 Endpoints

**System**

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | no | `{"status": "healthy", "version": "...", "environment": "...", "database": "connected"}` |

Returns 503 (not 200) when the database is unreachable — Docker `HEALTHCHECK`, Render, and Railway all key off the HTTP status code and ignore the body, so a degraded instance must not look healthy to them:

```json
{
  "status": "degraded",
  "version": "0.1.0",
  "environment": "production",
  "database": "unreachable"
}
```

**Auth**

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/auth/register` | no | Create account |
| POST | `/auth/login` | no | `{access_token, token_type, user}` |
| GET | `/auth/me` | yes | Current user |

**Jobs**

| Method | Path | Purpose |
|---|---|---|
| GET | `/jobs` | Paginated. `?search=&status=&page=&page_size=` |
| POST | `/jobs` | Create |
| GET | `/jobs/{id}` | Detail with candidate count, average score, top candidate |
| PATCH | `/jobs/{id}` | Update. Marks scores stale when description or skills change |
| DELETE | `/jobs/{id}` | Delete job, applications, scores. Candidates survive |

**Resumes**

| Method | Path | Purpose |
|---|---|---|
| POST | `/jobs/{job_id}/resumes` | Multipart batch upload. Returns per-file result |
| GET | `/candidates/{id}/resume-file` | Streams the original file for preview |

Upload response:

```json
{
  "job_id": 4,
  "uploaded": 48,
  "failed": 2,
  "results": [
    { "filename": "a.pdf", "status": "parsed", "candidate_id": 91 },
    { "filename": "b.pdf", "status": "parse_failed", "error": "No readable text found." }
  ]
}
```

**Candidates**

| Method | Path | Purpose |
|---|---|---|
| GET | `/candidates` | Paginated, filtered, sorted. See below |
| GET | `/candidates/{id}` | Full profile with skills |
| DELETE | `/candidates/{id}` | Remove candidate and file |
| PATCH | `/applications/{id}` | Update application status |

Query parameters on `/candidates`:

```text
job_id, search, min_score, max_score, skills (repeatable),
min_experience, education_level, status,
sort_by (fit_score|experience|created_at|name), sort_order (asc|desc),
page, page_size
```

**Scoring**

| Method | Path | Purpose |
|---|---|---|
| POST | `/jobs/{job_id}/score` | Score or rescore. Body `{candidate_ids?: [], force?: bool}` |
| GET | `/jobs/{job_id}/rankings` | Ranked list with score breakdowns |
| GET | `/candidates/{id}/score?job_id=` | Single breakdown |
| GET | `/candidates/{id}/skill-gap?job_id=` | Matched, missing, additional, percentage |
| GET | `/jobs/{job_id}/compare?candidate_ids=1,2,3` | Comparison matrix |

Score response:

```json
{
  "candidate_id": 21,
  "job_id": 4,
  "resume_match_score": 87.0,
  "skill_match_score": 75.0,
  "experience_score": 90.0,
  "education_score": 100.0,
  "final_fit_score": 84.8,
  "band": "good_match",
  "scoring_method": "embedding",
  "is_stale": false
}
```

**Interview questions**

| Method | Path | Purpose |
|---|---|---|
| POST | `/candidates/{id}/interview-questions` | Body `{job_id, count?, regenerate?}` |
| GET | `/candidates/{id}/interview-questions?job_id=` | Stored set |

**Attrition**

| Method | Path | Purpose |
|---|---|---|
| POST | `/attrition/predict` | Single employee feature dict |
| POST | `/attrition/predict/batch` | List of records |
| GET | `/attrition/employees` | Paginated employees with latest prediction |
| GET | `/attrition/model-info` | Model type, version, test metrics, feature list |

Prediction response:

```json
{
  "probability": 0.78,
  "risk_level": "high",
  "top_factors": [
    { "feature": "overtime", "contribution": 0.21 },
    { "feature": "job_satisfaction", "contribution": 0.17 }
  ],
  "model_version": "rf-v1"
}
```

**Analytics**

| Method | Path | Purpose |
|---|---|---|
| GET | `/analytics/overview` | Funnel counts, totals |
| GET | `/analytics/skills` | Top candidate skills, top missing skills |
| GET | `/analytics/scores` | Average fit score, distribution buckets |
| GET | `/analytics/attrition` | Risk band counts, average risk by department |

All accept `?job_id=` and `?from=&to=`.

**Export**

| Method | Path | Purpose |
|---|---|---|
| GET | `/jobs/{id}/export/csv` | CSV, accepts the same filters as `/candidates` |
| GET | `/jobs/{id}/export/pdf` | Shortlist report. Optional |

### 6.3 Status codes

| Code | Used for |
|---|---|
| 200 | Successful read or update |
| 201 | Resource created |
| 400 | Malformed request or business-rule violation |
| 401 | Missing or invalid token |
| 403 | Authenticated but not permitted |
| 404 | Resource does not exist |
| 409 | Conflict — duplicate email, already scored without `force` |
| 413 | File too large |
| 415 | Unsupported file type |
| 422 | Pydantic validation failure |
| 500 | Unhandled server error |
| 503 | LLM provider or model artefact unavailable |

---

## 7. Key request flows

### 7.1 Resume batch upload

```text
POST /jobs/{job_id}/resumes
   │
   ├─ validate job exists and is open
   ├─ for each file:
   │     ├─ validate extension, MIME, magic bytes, size          ─► fail → record, continue
   │     ├─ store as storage/{uuid}.{ext}
   │     ├─ text_extractor  (pdfplumber | python-docx)           ─► fail → parse_failed, continue
   │     ├─ text_cleaner
   │     ├─ guard: len(text) >= 100 chars                        ─► fail → parse_failed, continue
   │     ├─ field_extractor → name, email, phone, education, years, projects
   │     ├─ dedupe by email → update existing OR insert candidate
   │     ├─ skill_matcher → upsert candidate_skills
   │     └─ upsert application (candidate, job, status=new)
   │
   ├─ commit once per file, not once per batch
   └─ return per-file results
```

Per-file commit is deliberate: file 37 failing must not roll back files 1–36.

### 7.2 Scoring

```text
POST /jobs/{job_id}/score
   │
   ├─ load job, required skills, education ladder position
   ├─ select candidates (explicit ids, or all applied and unscored, or all if force)
   ├─ ranker = factory(config.SCORING_METHOD)
   ├─ for each candidate:
   │     ├─ resume_match  = ranker.score(resume_text, job_text)        → 0–100
   │     ├─ skill gap     = skill_gap(required, candidate_skills)
   │     ├─ skill_match   = matched_required / total_required × 100
   │     ├─ experience    = min(years / required_years, 1.0) × 100
   │     ├─ education     = ladder comparison → 100 / 70 / 40
   │     └─ final = weighted sum, rounded to 1 decimal
   ├─ upsert candidate_scores, is_stale = false
   └─ return summary
```

Embedding mode computes the job embedding once for the whole batch and reuses cached candidate embeddings.

### 7.3 Interview question generation

```text
POST /candidates/{id}/interview-questions
   │
   ├─ load candidate, job, skills, skill gap
   ├─ if stored questions exist and regenerate=false → return them, no LLM call
   ├─ build prompt from prompts.py: job, skills, experience, projects, missing skills
   ├─ call llm client (timeout 30s, one retry on transient error)
   ├─ parse strict JSON → validate against Pydantic schema
   │     └─ invalid → one repair retry → still invalid → 503 LLM_INVALID_OUTPUT
   ├─ drop questions failing the grounding check (anchors: skills, projects,
   │     certifications, and Experience-section prose — see interview_service.py)
   │     ├─ ≥5 survive  → 200, requested/generated/grounded, partial=false
   │     ├─ 1-4 survive → 200, shorter list, partial=true, logged at WARNING
   │     └─ 0 survive   → 503 INSUFFICIENT_GROUNDED_QUESTIONS
   ├─ persist with a shared generation_batch uuid
   └─ return questions
```

The `openai` provider targets any OpenAI-compatible Chat Completions
endpoint, not only OpenAI itself. `OPENAI_BASE_URL` selects which one. The
shipped configuration points it at Groq's endpoint, since a Claude
subscription does not include API credits and Groq's free tier covers
this project's volume. Leaving `OPENAI_BASE_URL` empty reaches real
OpenAI instead.

### 7.4 Attrition prediction

Two distinct artifact pairs are loaded, for two distinct purposes (Phase 11
— see Memory.md decision 70's calibration amendment and the completion
step in `ml/attrition/09_finalize_calibrated_model.py`):

- `calibrated_model.joblib` — a `CalibratedClassifierCV` (sigmoid) whose
  wrapped estimator already embeds preprocessing, SMOTE, and the classifier
  as one pipeline. Serves the calibrated probability. Takes the raw,
  unencoded 17-column feature row directly — never composed with a
  separate `preprocessor.transform()` call.
- `model.joblib` + `preprocessor.joblib` — the original uncalibrated
  Phase 10 artifacts, kept loaded for one purpose only: per-prediction
  `top_factors` (coefficient × encoded-value decomposition), matching the
  same naming convention already used in `metrics.json`'s global
  `feature_importances`. Never used to compute the served probability.

```text
Startup: lifespan loads calibrated_model.joblib (probability) +
         model.joblib + preprocessor.joblib (explanations) +
         feature_names.json + decision_threshold.json
         missing artefact, missing "calibrated" section, or missing
         "risk_tier" section → attrition endpoints return 503
         ATTRITION_MODEL_MISSING, everything else runs

POST /attrition/predict
   │
   ├─ validate feature dict against schema (INVALID_FEATURE_SET on any missing key)
   ├─ features.py orders the dict into the exact training feature order (feature_names.json)
   ├─ calibrated_model.predict_proba → the served, calibrated probability
   ├─ decision_threshold.json's "calibrated" threshold (0.2005) → flagged bool
   ├─ preprocessor.transform + model.coef_ → top_factors (per-prediction, signed)
   ├─ decision_threshold.json's "risk_tier" cutoffs → risk_level (low/medium/high),
   │     via attrition_service.compute_risk_tier() — F9.7 is resolved (owner
   │     decision, Memory.md, 2026-08-30): a frozen, ranking-derived scheme from
   │     the validated four-seed calibrated OOF distribution, loaded once at
   │     startup, never recomputed against the live employees table or a
   │     request's own population. Superseded the original fixed absolute-
   │     probability bands (<30%/30-60%/>60%) entirely.
   └─ persist prediction if employee_id supplied, return result
```

`risk_level`/binary `flagged` stay two separate concepts computed from two separate cutoffs (0.2005 for `flagged`, the frozen `risk_tier` cutoffs for `risk_level`) — neither is derived from the other.

---

## 8. Configuration

`.env.example` — committed, secrets left empty, every non-secret value pre-filled with a working default so a clone runs after filling in only the secrets:

```text
APP_ENV=development
API_V1_PREFIX=/api/v1
SECRET_KEY=
ACCESS_TOKEN_EXPIRE_MINUTES=1440

DATABASE_URL=sqlite:///./hiring.db

CORS_ORIGINS=http://localhost:5173

UPLOAD_DIR=./storage
MAX_UPLOAD_SIZE_MB=5
MAX_FILES_PER_BATCH=50

SCORING_METHOD=tfidf
EMBEDDING_MODEL=all-MiniLM-L6-v2
SEMANTIC_SKILL_MATCHING=false
WEIGHT_RESUME=0.40
WEIGHT_SKILL=0.35
WEIGHT_EXPERIENCE=0.15
WEIGHT_EDUCATION=0.10

LLM_PROVIDER=openai
# Valid LLM_MODEL ids depend on which endpoint OPENAI_BASE_URL targets.
# Check the provider's live model list before setting this - a model id
# that works today can be dropped without a rename (llama-3.3-70b-versatile
# was, without notice - see Memory.md). Do not take a model id from
# documentation alone.
LLM_MODEL=openai/gpt-oss-120b
# OPENAI_API_KEY and OPENAI_BASE_URL together target any OpenAI-compatible
# Chat Completions endpoint, not only OpenAI itself. The shipped value
# below points OPENAI_BASE_URL at Groq. Leaving OPENAI_BASE_URL empty
# reaches real OpenAI instead.
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.groq.com/openai/v1
ANTHROPIC_API_KEY=
LLM_TIMEOUT_SECONDS=30

ATTRITION_MODEL_PATH=../ml/attrition/artifacts/calibrated_model.joblib
```

`config.py` validates at import: `SCORING_METHOD` in the allowed set, `SECRET_KEY` non-empty outside development, the four scoring weights summing to 1.0, and `LLM_PROVIDER` being `openai` or `anthropic` with `LLM_MODEL` set whenever `LLM_PROVIDER=openai` (there is no safe built-in default model id, since one endpoint's valid ids don't carry over to another). Startup fails loudly rather than running misconfigured. `SEMANTIC_SKILL_MATCHING=true` is checked too, but only logs a startup warning — the feature it gates stays inert regardless until Phase 13 validates a real threshold (Phases.md), so there is nothing for it to fail on.

---

## 9. Frontend integration

The frontend is built and owned separately. The backend accommodates it.

**Contract points the backend guarantees:**

1. Base path `/api/v1`, JSON everywhere.
2. `Authorization: Bearer <token>`, obtained from `/auth/login`.
3. The error envelope in §6.1 for every non-2xx, so a single Axios interceptor can handle all failures.
4. CORS allows the origin listed in `CORS_ORIGINS`, with credentials disabled — the token travels in the header, not a cookie.
5. `snake_case` keys throughout. No mixed casing.
6. Enum values are lowercase snake strings, stable and safe to switch on.
7. Numbers are numbers. Scores are floats 0–100, probabilities floats 0–1. No pre-formatted strings, no `"87%"`.
8. Dates are ISO 8601 UTC.
9. Nullable fields are `null`, never omitted, never `""`.

**Integration procedure once the frontend is delivered:**

1. Read the frontend's API service layer and type definitions.
2. Produce a diff table: expected path, method, and payload versus what the backend exposes.
3. Change the backend to match. If a mismatch cannot be resolved backend-side, report it and stop — do not edit frontend files.
4. Add the frontend dev origin to `CORS_ORIGINS`.
5. Verify each page end to end against the live API before declaring integration complete.

---

## 10. Deployment topology

```text
Vercel                Render / Railway            Managed Postgres
┌──────────┐  HTTPS  ┌───────────────────┐  TCP  ┌──────────────┐
│ frontend │────────►│ uvicorn + FastAPI │──────►│  PostgreSQL  │
└──────────┘         │ model in memory   │       └──────────────┘
                     └─────────┬─────────┘
                               │ HTTPS
                               ▼
                         LLM provider API
```

Local parity via `docker-compose.yml` with three services: `backend`, `db` (postgres:16 with a named volume), and `frontend` if the owner chooses to containerise it. `ml/` is never a runtime service — artefacts are baked into the backend image or mounted.

Production notes: `--reload` off, worker count set explicitly, embedding and attrition models loaded once in the lifespan handler rather than per request, uploads on a persistent disk or object storage rather than the ephemeral container filesystem.
