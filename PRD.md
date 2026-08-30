# PRD — AI Hiring Intelligence Platform

**Version:** 1.0
**Status:** Approved for build
**Document owner:** Project owner
**Related docs:** `Architecture.md`, `Rules.md`, `Phases.md`, `Design.md`, `Memory.md` (created during Phase 1)

---

## 1. Overview

### 1.1 Problem

A single mid-level engineering role receives 200–500 applications. Recruiters currently:

- Read resumes manually, spending 6–8 seconds per resume, which is not enough to judge fit.
- Compare candidates from memory, with no consistent scoring standard between two recruiters or between Monday and Friday.
- Write interview questions from the job description alone, so questions are generic and never verify what the candidate actually claims on their resume.
- Have no visibility into whether the people they hire will still be there in eighteen months.

The result is slow shortlisting, inconsistent decisions, weak interviews, and expensive early attrition.

### 1.2 Solution

A web platform where a recruiter creates a job, uploads a batch of resumes, and receives a ranked, explainable shortlist. For every candidate the platform shows a fit score broken into its components, the exact skills matched and missing against the job, and a set of interview questions generated from that specific resume. A separate machine-learning module predicts attrition risk for existing employees using historical HR data.

The system is a decision-support tool. It ranks and explains. It never rejects a candidate on its own.

### 1.3 Non-goals

The following are explicitly out of scope for v1 and must not be built:

- Automatic rejection, auto-emailing candidates, or any candidate-facing interface.
- A candidate portal, job board, or public application form.
- Video interviewing, scheduling, or calendar integration.
- Offer management, payroll, or onboarding.
- Multi-tenant SaaS with organisation billing.
- Fine-tuning or self-hosting an LLM.
- A mobile application.

---

## 2. Target users

### 2.1 Primary — Recruiter / HR Executive

Screens candidates daily. Not technical. Needs speed and a defensible reason for every shortlist decision.

| Need | How the platform serves it |
|---|---|
| Reduce a 300-resume pile to a 15-person shortlist | Batch upload, automatic parsing, ranked list |
| Justify a decision to a hiring manager | Score breakdown, matched/missing skills, resume preview |
| Run a useful first-round interview | Resume-grounded questions with category and difficulty |
| Report on pipeline health | Analytics dashboard, CSV export |

### 2.2 Secondary — Hiring Manager

Reviews the shortlist the recruiter produces, does not upload resumes. Needs candidate comparison side by side and the skill-gap view before an interview.

### 2.3 Secondary — HR Analyst / HRBP

Works with existing employee data rather than candidates. Needs attrition risk scores, the factors driving each score, and risk distribution across departments.

### 2.4 Anti-user

The candidate. Candidates never log in, never see scores, and are never contacted by the system.

---

## 3. Core user flow

```text
Recruiter logs in
   ↓
Dashboard — open roles, pipeline counts, recent activity
   ↓
Create job — title, description, required skills, min experience, education, seniority
   ↓
Upload resumes to that job (PDF / DOCX, batch)
   ↓
Backend pipeline: text extraction → cleaning → field extraction → skill extraction → scoring
   ↓
Ranked candidate list for the job
   ↓
Open a candidate — fit score breakdown, matched/missing skills, resume preview
   ↓
Generate interview questions for that candidate
   ↓
Mark candidate shortlisted / interviewed / selected / rejected
   ↓
Compare shortlisted candidates side by side
   ↓
Export shortlist as CSV
```

Separate flow, not connected to the resume pipeline:

```text
HR Analyst → Attrition page → enter or select employee record
   ↓
Attrition probability + risk band + top contributing factors
   ↓
Risk distribution across the workforce
```

---

## 4. Feature specification

Features are grouped by module. Each has an ID used in `Phases.md`.

### F1 — Authentication and accounts

| ID | Feature | Detail |
|---|---|---|
| F1.1 | Register | Name, email, password. Email unique. Password hashed with bcrypt. |
| F1.2 | Login | Returns a JWT access token. Expiry 24h. |
| F1.3 | Current user | `GET /auth/me` returns the profile for the bearer token. |
| F1.4 | Route protection | Every endpoint except `/health`, `/auth/register`, `/auth/login` requires a valid token. |
| F1.5 | Roles | `recruiter`, `manager`, `analyst`, `admin`. Stored and returned. Enforcement in v1 is limited to blocking non-admin users from deleting jobs. |

Out of scope: password reset, email verification, OAuth, refresh-token rotation.

### F2 — Job management

| ID | Feature | Detail |
|---|---|---|
| F2.1 | Create job | Title, description (free text), required skills (list), min experience (years), education requirement, seniority, location. |
| F2.2 | List jobs | Paginated, searchable by title, filterable by status (`open` / `closed`). |
| F2.3 | Job detail | Job fields plus candidate count, average fit score, top candidate. |
| F2.4 | Edit job | Editing the description or required skills marks all existing scores for that job as stale. |
| F2.5 | Close / delete job | Close hides it from the default list. Delete cascades to scores and applications but never deletes candidate records or uploaded files. |

### F3 — Resume upload and parsing

| ID | Feature | Detail |
|---|---|---|
| F3.1 | Batch upload | Multipart upload of up to 50 files per request against one job. |
| F3.2 | Accepted formats | `.pdf` and `.docx` only. Max 5 MB per file. Rejected files are reported per-file, the rest of the batch still processes. |
| F3.3 | Text extraction | `pdfplumber` for PDF, `python-docx` for DOCX. Raw text stored on the candidate record. |
| F3.4 | Text cleaning | Normalise whitespace, strip page headers/footers, fix hyphenated line breaks, preserve section order. |
| F3.5 | Field extraction | Name, email, phone, education, total experience in years, skills, projects, certifications. |
| F3.6 | Duplicate handling | Same email uploaded again updates the existing candidate rather than creating a second one, and links them to the new job. |
| F3.7 | Parse failure | A resume that yields under 100 characters of text is stored with status `parse_failed` and surfaced in the UI with the reason. It is not silently dropped. |
| F3.8 | Original file access | The stored file is retrievable for the resume preview panel. |

Extraction targets for v1 (measured on a manually labelled set of at least 30 resumes):

| Field | Method | Target |
|---|---|---|
| Email | Regex | ≥ 95% |
| Phone | Regex | ≥ 90% |
| Name | Heuristic on first lines + spaCy `PERSON` | ≥ 75% |
| Education | Keyword and degree-pattern matching | ≥ 80% |
| Experience (years) | Date-range rules with NER fallback | ≥ 70% |

These are targets to measure against, not claims. Report the numbers actually obtained.

### F4 — Skill extraction

| ID | Feature | Detail |
|---|---|---|
| F4.1 | Skill dictionary | Curated JSON of canonical skills with aliases (`js` → `JavaScript`, `sklearn` → `scikit-learn`), each tagged `technical`, `tool`, `soft`, or `domain`. Minimum 250 entries. |
| F4.2 | Dictionary matching | Case-insensitive, word-boundary-safe matching against cleaned resume text. Must not match `R` inside `React` or `Go` inside `Google`. |
| F4.3 | Alias resolution | All matches are stored under the canonical name. |
| F4.4 | Semantic fallback | Where a required skill has no exact match, embedding similarity above a fixed threshold counts as a partial match and is labelled as such in the UI. |
| F4.5 | Job-side extraction | The same extractor runs on the job description so the recruiter does not have to list every required skill by hand. |

### F5 — Resume ranking

| ID | Feature | Detail |
|---|---|---|
| F5.1 | TF-IDF ranking (v1) | Vectorise resume text and job description, cosine similarity, scaled to 0–100. |
| F5.2 | Embedding ranking (v2) | `sentence-transformers` with `all-MiniLM-L6-v2`, cosine similarity, scaled to 0–100. |
| F5.3 | Switchable strategy | The active method is a configuration value, not a code change. Both remain available. |
| F5.4 | Batch scoring | Scoring 50 candidates against one job completes in under 60 seconds on a development machine. |
| F5.5 | Embedding cache | A candidate's resume embedding is computed once and reused across jobs. |

### F6 — Skill gap analysis

| ID | Feature | Detail |
|---|---|---|
| F6.1 | Matched skills | Intersection of job required skills and candidate skills. |
| F6.2 | Missing skills | Required skills with no candidate match. |
| F6.3 | Additional skills | Candidate skills outside the job requirements, shown separately. |
| F6.4 | Skill match percentage | `matched required / total required × 100`. |
| F6.5 | Partial matches | Semantic matches shown distinctly from exact matches. |

### F7 — Candidate fit score

| ID | Feature | Detail |
|---|---|---|
| F7.1 | Composite score | `resume_match × 0.40 + skill_match × 0.35 + experience × 0.15 + education × 0.10` |
| F7.2 | Configurable weights | Weights live in configuration and must sum to 1.0, validated at startup. |
| F7.3 | Experience sub-score | Ratio of candidate years to required years, capped at 100. Exceeding the requirement does not score above 100. |
| F7.4 | Education sub-score | Ordinal ladder against the job's education requirement. Meeting it scores 100, one level below scores 70, two or more below scores 40. |
| F7.5 | Score bands | ≥ 85 Strong Match · 70–84 Good Match · 55–69 Moderate Match · < 55 Weak Match. |
| F7.6 | Full breakdown | The API always returns all four sub-scores alongside the final score. A bare number is never returned on its own. |
| F7.7 | Stale detection | Scores carry the scoring method and a version. When the job changes, they are flagged stale and can be recomputed. |

### F8 — Interview question generation

| ID | Feature | Detail |
|---|---|---|
| F8.1 | Generate | 5–8 questions per candidate from the job description, candidate skills, experience, projects, and missing skills. |
| F8.2 | Categories | `technical`, `project`, `experience`, `skill_verification`, `behavioral`. |
| F8.3 | Difficulty | `easy`, `medium`, `hard`. |
| F8.4 | Resume grounding | Every question must reference something concrete from the resume. Generic questions such as "Tell me about yourself" are rejected. |
| F8.5 | Structured output | The LLM returns strict JSON, validated against a Pydantic schema. Malformed responses trigger one retry, then a clear error. |
| F8.6 | Persistence | Questions are stored so regeneration is not required on every page view. |
| F8.7 | Regenerate | The recruiter can explicitly regenerate, which replaces the stored set. |
| F8.8 | Graceful degradation | If the LLM provider is unavailable, the candidate page still loads with every other section intact and an inline message on the questions panel. |

### F9 — Attrition prediction

| ID | Feature | Detail |
|---|---|---|
| F9.1 | Dataset | A public HR attrition dataset. Trained offline in `ml/`, never trained from resumes. |
| F9.2 | EDA | Cleaning, distributions, and attrition rate broken down by salary, department, overtime, satisfaction, tenure, and promotion history. |
| F9.3 | Model comparison | Logistic Regression, Random Forest, and XGBoost compared on accuracy, precision, recall, F1, and ROC-AUC. |
| F9.4 | Class imbalance | Imbalance measured and handled with class weighting or resampling, with before/after results reported. |
| F9.5 | Explainability | Feature importance returned per prediction. SHAP values if time allows. |
| F9.6 | Serving | Serialised model loaded once at startup and served over the API. |
| F9.7 | Risk bands | < 30% Low · 30–60% Medium · > 60% High. |
| F9.8 | Batch prediction | Multiple employee records scored in one request. |
| F9.9 | Protected attributes | Gender, marital status, age band, and any other sensitive attribute are excluded from the feature set. Their exclusion is documented. |

### F10 — Analytics dashboard

| ID | Feature | Detail |
|---|---|---|
| F10.1 | Pipeline funnel | Total, shortlisted, interviewed, selected, rejected. |
| F10.2 | Skill demand | Most common candidate skills; most frequently missing skills across the pipeline. |
| F10.3 | Candidate quality | Average fit score per job and score distribution histogram. |
| F10.4 | Attrition overview | Count by risk band and average risk by department. |
| F10.5 | Filters | Filter analytics by job and by date range. |

### F11 — Candidate comparison

| ID | Feature | Detail |
|---|---|---|
| F11.1 | Multi-select | 2–4 candidates within the same job. |
| F11.2 | Comparison matrix | Fit score, resume match, skill match, experience, education, matched skills, missing skills. |
| F11.3 | Best-per-row | The leading value in each row is marked. |

### F12 — Search, filter, sort

| ID | Feature | Detail |
|---|---|---|
| F12.1 | Search | Candidate name, email, or skill substring. |
| F12.2 | Filters | Min fit score, required skill present, min experience, education level, application status. |
| F12.3 | Combined filters | Filters combine with AND. |
| F12.4 | Sort | Fit score, experience, upload date, name. Ascending and descending. |
| F12.5 | Server-side | Filtering, sorting, and pagination all happen in the database, never in the browser. |

### F13 — Export

| ID | Feature | Detail |
|---|---|---|
| F13.1 | CSV export | Candidate, fit score, resume match, skill match, experience, education, missing skills, status. |
| F13.2 | Filter-aware | Export respects the currently applied filters. |
| F13.3 | PDF shortlist | A formatted shortlist report. Optional, lowest priority in scope. |

### F14 — Evaluation

| ID | Feature | Detail |
|---|---|---|
| F14.1 | Ranking metrics | Precision@K, Recall@K, and NDCG on a manually labelled evaluation set. |
| F14.2 | Extraction metrics | Precision, recall, and F1 for skill extraction. |
| F14.3 | Attrition metrics | Precision, recall, F1, and ROC-AUC on a held-out test set. |
| F14.4 | LLM evaluation | Human rating 1–5 for relevance, specificity, technical quality, and resume grounding on a fixed sample. |
| F14.5 | Results file | All measured numbers recorded in `docs/EVALUATION.md`. Only measured numbers are recorded. |

---

## 5. Requirements that apply across the product

### 5.1 Performance

| Operation | Target |
|---|---|
| Standard API read | < 300 ms |
| Single resume parse | < 3 s |
| Batch of 50 resumes, parse and score | < 90 s |
| Interview question generation | < 15 s |
| Attrition prediction | < 500 ms |
| Analytics dashboard load | < 1.5 s |

### 5.2 Reliability

- One failed resume never aborts a batch.
- LLM failure never blocks any other feature.
- A missing attrition model artefact returns a clear error from the attrition endpoints and leaves every other endpoint working.

### 5.3 Security

- Passwords hashed with bcrypt. Never returned by any endpoint.
- JWT bearer authentication on all protected routes.
- Uploads validated by extension, MIME type, and magic bytes. Stored under a generated UUID filename, never the client-supplied name.
- Secrets in `.env`, which is gitignored. `.env.example` lists keys with empty values.
- CORS restricted to a configured origin list.
- Resume text is sent to the LLM provider only when the recruiter explicitly triggers question generation, and this is stated in the UI and README.

### 5.4 Ethics — binding product requirements, not commentary

- The system ranks and explains. It never auto-rejects.
- Every score is shown with its full breakdown. No opaque numbers.
- Attrition output is a probability, always displayed as a probability, never as a verdict about a person.
- Sensitive attributes are excluded from all models.
- A recruiter can always open the original resume and disagree with the score.
- README carries an Ethical Considerations section covering historical bias in ranking, the assistive role of the system, and the need for ongoing bias and drift monitoring.

---

## 6. Success criteria

The build is complete when all of the following hold:

1. A recruiter can register, log in, create a job, upload 50 mixed PDF and DOCX resumes, and see a ranked list, with no manual backend step in between.
2. Every candidate detail view shows a fit score with all four components, matched and missing skills, and the original resume.
3. Interview questions generate for any candidate and are specific enough that a reader can tell which resume produced them.
4. Attrition prediction returns a probability, a risk band, and contributing factors from a model trained in `ml/` and served through the API.
5. The analytics dashboard renders all four chart groups from live database data.
6. CSV export downloads and matches the on-screen filtered list.
7. Every measured metric in `docs/EVALUATION.md` is a real number produced by a real evaluation run.
8. The whole stack runs from a documented local setup and from `docker-compose up`.
9. The README follows the agreed structure and documents limitations honestly.

---

## 7. Ownership boundary

The frontend is authored and owned by the project owner, not generated as part of this build. The backend is built to serve it.

- `frontend/` is read-only for the purposes of this build. No file inside it is created, edited, reformatted, or restyled.
- The backend defines the API contract in `Architecture.md`. Once the frontend exists, it is inspected and the backend is adapted to match its actual expectations. The frontend is not adapted to the backend.
- `Design.md` documents the visual system for reference and for any backend-rendered output such as the PDF shortlist. It is a record of the design, not an instruction to build UI.
