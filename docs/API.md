# API Reference

Generated summary of the actual backend contract. Updated whenever the contract changes (Rules.md §8) — most recently to add the `POST /jobs/{job_id}/resumes` section, live since Phase 4 but never documented here until the Phase 14 frontend build surfaced the gap (2026-09-06); no backend behavior changed. Before that, most recently for Phase 12 (analytics, comparison, candidate filtering, CSV export).

Base path: `/api/v1`. All responses are JSON. All routes except `/health`, `/auth/register`, and `/auth/login` require `Authorization: Bearer <token>`.

Every non-2xx response uses the same error envelope:

```json
{
  "error": {
    "code": "STABLE_MACHINE_CODE",
    "message": "Safe to display to the user.",
    "details": {}
  }
}
```

A paginated list response always has this shape:

```json
{
  "items": [],
  "total": 137,
  "page": 1,
  "page_size": 20,
  "pages": 7
}
```

---

## System

### `GET /health` — no auth

Returns 200 when the database is reachable:

```json
{
  "status": "healthy",
  "version": "0.1.0",
  "environment": "development",
  "database": "connected"
}
```

Returns **503** (not 200) when the database is unreachable — Docker `HEALTHCHECK`, Render, and Railway key off the HTTP status code, not the body:

```json
{
  "status": "degraded",
  "version": "0.1.0",
  "environment": "development",
  "database": "unreachable"
}
```

---

## Auth

### `POST /auth/register` — no auth

Request:

```json
{ "name": "Ada Lovelace", "email": "ada@example.com", "password": "correct-horse-battery" }
```

`role` is not an accepted field — the schema uses `extra="forbid"`, so including it (e.g. `"role": "admin"`) fails validation with **422 `REQUEST_VALIDATION_ERROR`** rather than being silently ignored or honored. Every registration is a `recruiter`; there is no v1 mechanism to self-assign another role.

Response — **201**:

```json
{
  "id": 1,
  "name": "Ada Lovelace",
  "email": "ada@example.com",
  "role": "recruiter",
  "created_at": "2026-08-26T18:00:46"
}
```

Duplicate email — **409**:

```json
{
  "error": {
    "code": "DUPLICATE_EMAIL",
    "message": "An account with this email already exists.",
    "details": { "email": "ada@example.com" }
  }
}
```

### `POST /auth/login` — no auth

Request: `{ "email": "ada@example.com", "password": "correct-horse-battery" }`

Response — **200**:

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "name": "Ada Lovelace",
    "email": "ada@example.com",
    "role": "recruiter",
    "created_at": "2026-08-26T18:00:46"
  }
}
```

Wrong password — **401**:

```json
{ "error": { "code": "INVALID_CREDENTIALS", "message": "Incorrect email or password.", "details": {} } }
```

### `GET /auth/me` — auth required

Response — **200**: same `user` shape as above.

No token — **401** `TOKEN_MISSING`. Malformed token — **401** `TOKEN_INVALID`. Expired token — **401** `TOKEN_EXPIRED`. Valid token for a since-deleted user — **401** `INVALID_CREDENTIALS`.

```json
{ "error": { "code": "TOKEN_MISSING", "message": "Authentication required.", "details": {} } }
```

---

## Jobs

All routes require auth. `DELETE /jobs/{id}` additionally requires the `admin` role.

### `GET /jobs` — auth required

Query parameters: `search` (title substring, case-insensitive), `status` (`open` | `closed` | `all`, default `open` — closed jobs are hidden from the default list per PRD F2.5), `page` (default 1), `page_size` (default 20, max 100).

Response — **200**, `Page[JobResponse]`:

```json
{
  "items": [
    {
      "id": 1,
      "title": "Backend Engineer",
      "description": "...",
      "required_skills": ["Python", "FastAPI", "PostgreSQL"],
      "min_experience_years": 2.0,
      "education_requirement": "Bachelor's",
      "seniority": "mid",
      "location": "Remote",
      "status": "open",
      "created_by": 1,
      "created_at": "2026-08-26T18:00:46",
      "updated_at": "2026-08-26T18:00:46"
    }
  ],
  "total": 50,
  "page": 1,
  "page_size": 20,
  "pages": 3
}
```

### `POST /jobs` — auth required

Request:

```json
{
  "title": "Backend Engineer",
  "description": "Build and maintain REST APIs.",
  "required_skills": ["Python", "FastAPI"],
  "min_experience_years": 2.0,
  "education_requirement": "Bachelor's",
  "seniority": "mid",
  "location": "Remote"
}
```

Response — **201**: a `JobResponse` (shape above). `status` defaults to `open`; `created_by` is set from the bearer token.

### `GET /jobs/{id}` — auth required

Response — **200**, `JobDetailResponse`: every `JobResponse` field plus:

```json
{
  "candidate_count": 0,
  "average_fit_score": null,
  "top_candidate": null
}
```

`candidate_count` is a real count (0 is a true fact about an empty job). `average_fit_score` and `top_candidate` are `null` — not `0.0` — until at least one score exists; once scores exist, `top_candidate` looks like `{"candidate_id": 21, "name": "...", "final_fit_score": 84.8}`.

Nonexistent job — **404**:

```json
{ "error": { "code": "JOB_NOT_FOUND", "message": "Job not found.", "details": { "job_id": 999999 } } }
```

### `GET /jobs/{id}/suggested-skills` — auth required

Runs the same dictionary skill matcher used on resumes against the job's `description`, and returns whatever it finds that isn't already in `required_skills` (case-insensitive comparison). **Read-only** — nothing is written to `required_skills`; the recruiter reviews these and adds what they want via `PATCH /jobs/{id}` (PRD F4.5). Mutating `required_skills` automatically was considered and deliberately rejected: the recruiter couldn't tell what they typed from what was inferred, couldn't remove an inferred skill without it reappearing on the next description edit, and it would interfere with the stale-marking behavior above.

Captured from a real job with `description: "...skilled in Python and Docker experience."` and `required_skills: ["Python"]`:

```json
{
  "job_id": 1,
  "suggested": [
    { "canonical": "Docker", "type": "tool" }
  ]
}
```

Nonexistent job — **404** `JOB_NOT_FOUND`.

### `PATCH /jobs/{id}` — auth required

Any subset of the `POST /jobs` fields, plus `status`. Only a *value change* to `description` or `required_skills` marks that job's existing scores `is_stale = true` (PRD F2.4) — reordering `required_skills` without changing its contents does not count as a change, and editing `title`/`location`/`seniority`/`education_requirement`/`min_experience_years`/`status` never marks scores stale. An explicit `null` for any field is rejected with **422** (every field is optional to omit, but none of the underlying columns are nullable).

Response — **200**: the updated `JobResponse`.

### `DELETE /jobs/{id}` — admin role required

Deletes the job; the database cascades to that job's `applications`, `candidate_scores`, and `interview_questions`. Candidate rows are never touched.

Response — **200**: `{ "id": 4, "deleted": true }`.

Authenticated but not an admin — **403**:

```json
{ "error": { "code": "ADMIN_REQUIRED", "message": "Only administrators can perform this action.", "details": {} } }
```

No token — **401** (checked before the role check).

---

## Resumes

### `POST /jobs/{job_id}/resumes` — auth required

`multipart/form-data`, one or more `files` parts (PDF or DOCX). This endpoint was live from Phase 4 but missing from this document until now — added here, not newly built.

Every file is validated (extension, then MIME type, then magic bytes, then size, cheapest first) and text-extracted independently — one bad file never fails the batch. A file whose extracted text is under 100 characters (e.g. a scanned image PDF) is recorded as `parse_failed` with `RESUME_TEXT_TOO_SHORT`, not silently dropped or treated as an empty candidate. An email match against an existing candidate updates that candidate and adds a new `Application` to this job, rather than creating a duplicate person (Phase 5); a resume with no extractable email can never dedupe-match another for the same reason.

Only three conditions abort the whole call before any file is processed — job not found, an empty file list, or exceeding `MAX_FILES_PER_BATCH` (50, `.env`) — every other failure (unsupported type, oversized, corrupt, parse failure) is embedded per-file in a **200** response:

```json
{
  "job_id": 1,
  "uploaded": 8,
  "failed": 2,
  "results": [
    { "filename": "grace_hopper.pdf", "status": "parsed", "candidate_id": 12, "code": null, "error": null },
    { "filename": "scanned.pdf", "status": "parse_failed", "candidate_id": 13, "code": "RESUME_TEXT_TOO_SHORT", "error": "Extracted text is too short to be a usable resume." },
    { "filename": "notes.txt", "status": "parse_failed", "candidate_id": null, "code": "UNSUPPORTED_FILE_TYPE", "error": "Only PDF and DOCX files are supported." }
  ]
}
```

`candidate_id` is `null` only for a Tier-1 validation failure (extension/MIME/magic-bytes/size) — the file was never accepted, so no candidate row exists for it. Every other outcome, including a Tier-2 parse failure, has a real `candidate_id`.

Request-level failures, before any file is touched:

```json
{ "error": { "code": "NO_FILES_PROVIDED", "message": "No files were provided.", "details": {} } }
```

Nonexistent job — **404** `JOB_NOT_FOUND`. More than `MAX_FILES_PER_BATCH` files — **400** `BATCH_LIMIT_EXCEEDED`.

---

## Candidates

All routes require auth. No role restriction (F1.5 limits role enforcement to job delete only).

### `GET /candidates` — auth required

Query parameters (Phase 12, PRD F12 — all executed in SQL, never a Python post-filter):

```text
job_id, search, min_score, max_score, skills (repeatable),
min_experience, education_level, status,
sort_by (fit_score|experience|created_at|name), sort_order (asc|desc),
page, page_size
```

- `job_id` restricts to candidates with an `Application` to that job.
- `search` matches candidate name, email, or a skill name substring (case-insensitive `OR`).
- `min_score`/`max_score` filter on `final_fit_score` — the specific job's score when `job_id` is given, otherwise each candidate's own best (highest) score across every job they've been scored for.
- `skills` is repeatable and combines with `AND`: a candidate must have every listed skill, not any one of them.
- `min_experience` excludes a candidate with unknown (`null`) `experience_years` rather than treating unknown as passing.
- `education_level` is an exact match against the ladder position, not a minimum.
- `status` filters on `Application.status` — scoped to `job_id`'s application when both are given, otherwise "has at least one application in this status."
- Every filter combines with every other as SQL `AND` — e.g. `min_score=80&skills=Python&min_experience=2` returns only candidates satisfying all three.
- Sorting always adds `candidates.id ASC` as a secondary key, so ties resolve identically on every call (stable, deterministic). A `null` value on the sort column (e.g. `sort_by=fit_score` for an unscored candidate) always sorts last, in both directions.

Response — **200**, `Page[CandidateListItem]` (`CandidateResponse` plus `fit_score`):

```json
{
  "items": [
    {
      "id": 1,
      "name": "Grace Hopper",
      "email": "grace@example.com",
      "phone": null,
      "education": "Master's",
      "education_level": 3,
      "experience_years": 12.0,
      "projects": [],
      "certifications": [],
      "parse_status": "parsed",
      "parse_error": null,
      "created_at": "2026-08-26T18:15:24",
      "fit_score": 84.8
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "pages": 1
}
```

`resume_text`, `resume_path`, and `embedding` never appear in any candidate response — the first is a privacy boundary (Rules.md §7), the others are internal storage/ML details.

### `GET /candidates/{id}` — auth required

Response — **200**, `CandidateDetailResponse`: every `CandidateResponse` field plus `skills`, grouped by type (Phase 5). All four keys are always present, even when empty — captured from a real candidate with a two-column DOCX resume (`Figma`/`Sketch`/`HTML`/`CSS` matched, no soft or domain skills on this resume):

```json
{
  "skills": {
    "technical": [
      { "skill_name": "HTML", "skill_type": "technical", "source": "dictionary" },
      { "skill_name": "CSS", "skill_type": "technical", "source": "dictionary" }
    ],
    "tool": [
      { "skill_name": "Figma", "skill_type": "tool", "source": "dictionary" },
      { "skill_name": "Sketch", "skill_type": "tool", "source": "dictionary" }
    ],
    "soft": [],
    "domain": []
  }
}
```

`source` is always `"dictionary"` in Phase 5 — `"semantic"` doesn't exist until Phase 7's embedding fallback (PRD F4.4).

Nonexistent candidate — **404** `CANDIDATE_NOT_FOUND`.

### `DELETE /candidates/{id}` — auth required

Removes the candidate row; the database cascades to their `candidate_skills`, `applications`, `candidate_scores`, and `interview_questions`. The stored resume file is also deleted, after the DB commit succeeds (Phase 4 decision 23).

Response — **200**: `{ "id": 7, "deleted": true }`.

### `PATCH /applications/{id}` — auth required

Request: `{ "status": "shortlisted" }` — any `ApplicationStatus` value (`new`, `shortlisted`, `interviewed`, `selected`, `rejected`) is accepted; there is no transition state machine in v1.

Response — **200**, `ApplicationResponse`. Nonexistent application — **404** `APPLICATION_NOT_FOUND`.

---

## Scoring

All routes require auth. Scoring runs TF-IDF cosine similarity (PRD F5.1) — a fresh vectoriser is fitted per call on the job description plus every applicant's resume text, then discarded (Rules.md §4.6); nothing is cached across calls.

### `POST /jobs/{job_id}/score` — auth required

Request: `{ "candidate_ids": null, "force": false }` (both optional; posting `{}` is equivalent).

- `candidate_ids` omitted/`null`: scores every applied candidate with no existing score, or an existing score flagged `is_stale`. Already-scored, non-stale candidates are left untouched.
- `force: true`: rescores every applied candidate regardless of prior state.
- `candidate_ids: [...]`: scores exactly those candidates (each must have an `Application` to this job — one that doesn't is skipped with `CANDIDATE_NOT_APPLIED`, not a hard failure). Takes priority over `force`.

A candidate whose resume has no usable text (parse failed, or empty) is skipped with a reason, not scored zero — no `candidate_scores` row is written for them at all. Captured from a real run — one candidate scored, one candidate (`corrupt.pdf`) skipped:

```json
{
  "job_id": 1,
  "scored": 1,
  "skipped": 1,
  "results": [
    { "candidate_id": 1, "status": "scored", "final_fit_score": 38.1, "code": null, "reason": null },
    {
      "candidate_id": 2,
      "status": "skipped",
      "final_fit_score": null,
      "code": "RESUME_TEXT_TOO_SHORT",
      "reason": "Candidate has no usable resume text (parse failed)."
    }
  ]
}
```

A job with no `required_skills` — **400**, before any candidate is touched:

```json
{
  "error": {
    "code": "JOB_HAS_NO_SKILLS",
    "message": "This job has no required skills; skill match cannot be computed.",
    "details": { "job_id": 2 }
  }
}
```

Nonexistent job — **404** `JOB_NOT_FOUND`.

With `SCORING_METHOD=embedding` and the embedding model unavailable (missing/uncached with no network, or a corrupted download) — **503**, the whole call fails loudly rather than recording every candidate as an individually failed skip, since the operator's configured ranking method itself is broken:

```json
{
  "error": {
    "code": "EMBEDDING_MODEL_UNAVAILABLE",
    "message": "Could not load the embedding model 'all-MiniLM-L6-v2': ...",
    "details": {}
  }
}
```

`SCORING_METHOD=tfidf` is never affected by this — it never touches the embedding model at all, even if it's broken.

### `GET /jobs/{job_id}/rankings` — auth required

Paginated (`page`, `page_size`), ordered by `final_fit_score` descending. Each item is the full score breakdown below plus `candidate_name`/`candidate_email` for display.

```json
{
  "items": [
    {
      "candidate_id": 1,
      "job_id": 1,
      "resume_match_score": 3.5,
      "skill_match_score": 33.3,
      "experience_score": 100.0,
      "education_score": 100.0,
      "final_fit_score": 38.1,
      "band": "weak_match",
      "scoring_method": "tfidf",
      "score_version": 2,
      "is_stale": false,
      "excluded_sub_scores": [],
      "candidate_name": "Aaron Whitfield",
      "candidate_email": "aaron.whitfield@example.com"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "pages": 1
}
```

Nonexistent job — **404** `JOB_NOT_FOUND`.

### `GET /candidates/{id}/score?job_id=` — auth required

```json
{
  "candidate_id": 1,
  "job_id": 1,
  "resume_match_score": 3.5,
  "skill_match_score": 33.3,
  "experience_score": 100.0,
  "education_score": 100.0,
  "final_fit_score": 38.1,
  "band": "weak_match",
  "scoring_method": "tfidf",
  "score_version": 2,
  "is_stale": false,
  "excluded_sub_scores": []
}
```

`experience_score`/`education_score` are `null` — not `0.0` — when the candidate's `experience_years`/`education_level` is unknown (an extraction gap, not a real zero). `excluded_sub_scores` names exactly which sub-score(s) were dropped from `final_fit_score`, with the remaining weights renormalized to sum to 1.0, e.g. `["experience"]`.

No score exists yet for this candidate/job pair — **404**:

```json
{
  "error": {
    "code": "SCORE_NOT_FOUND",
    "message": "No score exists for this candidate and job.",
    "details": { "candidate_id": 1, "job_id": 999999 }
  }
}
```

### `GET /candidates/{id}/skill-gap?job_id=` — auth required

Reads the same `matched_skills`/`missing_skills`/`additional_skills`/`skill_match_score` already computed and stored by the most recent scoring run (no recomputation) — a candidate/job pair with no score yet returns the same `SCORE_NOT_FOUND` as above.

Since Phase 7, each entry in `matched` carries a `source` (`dictionary` or `semantic`, F4.4) instead of `matched` being a plain list of names — a dictionary match is an exact skill-name match; a semantic match means the required skill had no exact match but scored above the (currently unmeasured — see "Known limitations" in `docs/EVALUATION.md`) similarity threshold against one of the candidate's own skills, named in `matched_via`. Semantic matching is opt-in (`SEMANTIC_SKILL_MATCHING=false` by default) and, when active, contributes half credit toward `percentage`, not full credit — Design.md renders it as a visually distinct chip (hollow dot, dashed border) for the same reason. `missing`/`additional` are unchanged, plain name lists — with `SEMANTIC_SKILL_MATCHING=false` (the default), every entry in `matched` has `source: "dictionary"` and `matched_via: null`, identical in substance to the pre-Phase-7 shape:

```json
{
  "candidate_id": 1,
  "job_id": 1,
  "matched": [
    { "skill": "Python", "source": "dictionary", "matched_via": null }
  ],
  "missing": ["FastAPI", "SQL"],
  "additional": ["Go", "gRPC", "Distributed Systems", "Kubernetes", "Terraform", "PostgreSQL", "Redis"],
  "percentage": 33.3
}
```

With `SEMANTIC_SKILL_MATCHING=true`, a required skill with no exact match can be promoted — captured from a real run where the job required `Node.js` and the candidate's own extracted skills included `Express.js` but not `Node.js` itself (a candidate skill promoted this way can still also appear in `additional`, since it genuinely is one of the candidate's own skills outside the literal requirement list — `Express.js` does here):

```json
{
  "candidate_id": 1,
  "job_id": 1,
  "matched": [
    { "skill": "Python", "source": "dictionary", "matched_via": null },
    { "skill": "PostgreSQL", "source": "dictionary", "matched_via": null },
    { "skill": "Node.js", "source": "semantic", "matched_via": "Express.js" }
  ],
  "missing": [],
  "additional": ["Express.js"],
  "percentage": 83.3
}
```

### `GET /jobs/{id}/compare?candidate_ids=` — auth required (Phase 12, F11)

`candidate_ids` is one comma-joined query value (`?candidate_ids=12,17,33`), not a repeatable parameter — 2 to 4 ids. Every id must have a `CandidateScore` row for this specific job (i.e. have been scored for it); an id that doesn't returns `SCORE_NOT_FOUND` naming exactly which ones are missing, not a partial matrix.

Response is a per-metric matrix, not a per-candidate list, so `best_candidate_id` can be marked once per row rather than the caller re-deriving it: `direction` names which way "best" points for that specific metric (`higher_is_better` for every `*_score` field and `matched_skills_count`; `lower_is_better` for `missing_skills_count` — the marking is never a hardcoded "highest wins"). A tie is broken by the lowest `candidate_id`, so the response is identical across repeated calls with the same input. Full matched/missing skill lists (not just counts) are on each entry in `candidates`, for F11.2's "matched skills, missing skills" fields.

```json
{
  "job_id": 4,
  "candidate_ids": [12, 17, 33],
  "candidates": [
    {
      "candidate_id": 12,
      "candidate_name": "Grace Hopper",
      "matched_skills": [{ "skill": "Python", "source": "dictionary", "matched_via": null }],
      "missing_skills": ["FastAPI"]
    }
  ],
  "matrix": [
    {
      "metric": "final_fit_score",
      "label": "Fit Score",
      "direction": "higher_is_better",
      "values": { "12": 84.8, "17": 76.2, "33": 91.0 },
      "best_candidate_id": 33
    },
    {
      "metric": "missing_skills_count",
      "label": "Missing Skills",
      "direction": "lower_is_better",
      "values": { "12": 1, "17": 2, "33": 0 },
      "best_candidate_id": 33
    }
  ]
}
```

`INVALID_CANDIDATE_COUNT` (400) covers both an out-of-[2,4]-bounds count and a malformed `candidate_ids` value (non-integer parts) — either way, nothing usable was requested.

---

## Interview questions

### `POST /candidates/{id}/interview-questions` — auth required

Body: `{ "job_id": int, "count"?: int (5-8, default 8), "regenerate"?: bool (default false) }`.

If questions already exist for this candidate/job pair and `regenerate` is not `true`, the stored set is returned directly — no LLM call is made. Otherwise the configured LLM provider is called to generate `count + 2` questions (a buffer against the grounding filter below), of which up to `count` grounded ones are kept and persisted under one `generation_batch` UUID. `regenerate: true` deletes the previously stored set for this pair before generating — it replaces, never appends.

Every kept question is checked against a grounding filter (F8.4): it must contain at least one concrete detail drawn from the candidate's own extracted skills, projects, certifications, or Experience-section resume text (never from the job posting). This is word-boundary-safe substring matching against a candidate-specific allowlist, not semantic understanding — see `docs/EVALUATION.md`'s Phase 8 section for exactly what it does and does not catch.

The response always carries the grounding-filter outcome, not just the question list, so a caller never has to infer a short list's meaning from its length: `requested` (the `count` asked for), `generated` (what the model returned before filtering), `grounded` (how many survived the filter, before any count truncation), and `partial` (`true` when `grounded` is below 5). These four are persisted per batch, so a later `GET` or a cached "stored, not regenerating" `POST` carries the same values a fresh generation would.

- `grounded >= 5`: 200, `partial: false`, up to `count` questions returned.
- `1 <= grounded < 5`: 200, `partial: true`, the shorter set is returned as-is (logged server-side at `WARNING`).
- `grounded == 0`: 503 `INSUFFICIENT_GROUNDED_QUESTIONS` — every generated question was well-formed but none referenced anything in the candidate's own data. Distinct from `LLM_INVALID_OUTPUT` below, which is a model-output problem, not a filter one.

The candidate's full resume text is sent to the configured LLM provider as part of this call — including any name, email, and phone it contains, unredacted (Rules.md §7's one explicit, consented exception to resume text never leaving the system).

```json
{
  "candidate_id": 1,
  "job_id": 1,
  "generation_batch": "ddd6c999-c688-4e0a-9687-9cc39bb5cbae",
  "requested": 8,
  "generated": 10,
  "grounded": 10,
  "partial": false,
  "questions": [
    {
      "id": 1,
      "question": "Walk me through how StockWatch handles concurrent inventory updates.",
      "category": "project",
      "difficulty": "medium",
      "rationale": "StockWatch is a real project on the resume; probes design depth.",
      "generation_batch": "ddd6c999-c688-4e0a-9687-9cc39bb5cbae",
      "created_at": "2026-08-28T10:28:55"
    },
    {
      "id": 4,
      "question": "How would you extend StockWatch to run on Kubernetes?",
      "category": "skill_verification",
      "difficulty": "hard",
      "rationale": "Kubernetes is required but not on the candidate's skill list.",
      "generation_batch": "ddd6c999-c688-4e0a-9687-9cc39bb5cbae",
      "created_at": "2026-08-28T10:28:55"
    }
  ]
}
```

Failure modes, all 503 unless noted: `LLM_UNAVAILABLE` (provider key missing or the provider call failed, after one retry on a transient error), `LLM_TIMEOUT` (timed out, after one retry), `LLM_INVALID_OUTPUT` (the model's JSON was unusable after one repair attempt), `INSUFFICIENT_GROUNDED_QUESTIONS` (zero generated questions survived the grounding filter — see above). Before any provider call: `JOB_HAS_NO_SKILLS` (400) if the job has no required skills, `RESUME_TEXT_TOO_SHORT` (400) if the candidate has no usable extracted resume text.

### `GET /candidates/{id}/interview-questions?job_id=` — auth required

Read-only — never calls the LLM. Returns the stored set for this candidate/job pair, or `404 INTERVIEW_QUESTIONS_NOT_FOUND` if nothing has been generated yet:

```json
{
  "error": {
    "code": "INTERVIEW_QUESTIONS_NOT_FOUND",
    "message": "No interview questions have been generated for this candidate and job yet.",
    "details": { "candidate_id": 2, "job_id": 1 }
  }
}
```

---

## Attrition

The model is loaded once, at application startup (not per request — PRD F9.6, Rules.md 4.6). If the artifact set is missing or inconsistent, every route below returns 503 `ATTRITION_MODEL_MISSING`; every other endpoint in the API stays healthy.

Three concepts every prediction response keeps separate, never conflated (Memory.md decisions 67/69/70/72):

1. `probability` — the sigmoid-calibrated probability itself (never the raw SMOTE classifier's own, uncalibrated output, which overstates real attrition risk by roughly 2.3–2.4x).
2. `flagged` / `decision_threshold` — the binary operating cutoff (`0.2005`, the sigmoid-calibrated threshold — a different number from, and not a transform of, the `0.550` cutoff `ml/attrition/04_evaluate.py` uses for its own offline evaluation).
3. `risk_level` / `risk_level_status` — the display risk tier. **F9.7 is resolved** (owner decision, Memory.md, 2026-08-30): `risk_level` is always exactly one of `low`/`medium`/`high` for a valid prediction, computed by a frozen, ranking-derived scheme built from the validated four-seed calibrated out-of-fold probability distribution — **not** the original PRD F9.7 fixed absolute-probability bands (`<30%`/`30-60%`/`>60%`), which this supersedes entirely, and **not** a live percentile rank against the current `employees` table (the cutoffs are frozen at derivation time and loaded once at startup, exactly like `decision_threshold`). See `GET /attrition/model-info` for the exact cutoffs and full derivation metadata, and `docs/EVALUATION.md`'s Phase 10 calibration amendment for the underlying discrimination evidence (`attrition_service.py`'s `compute_risk_tier()`, a pure function of `(probability, high_cutoff, medium_cutoff)` — never a database query).

Gender, marital status, and "Over18" (Phase 9's excluded protected attributes) are not accepted fields on any attrition request — supplying one is rejected outright (`422`, `extra="forbid"`, the same convention used for `UserCreate`), not silently dropped.

### `POST /attrition/predict` — auth required

Body: the 17 canonical business features (all required; each reported by name if missing — see below), plus an optional `employee_id`. When `employee_id` is supplied, it must reference an existing `employees` row (`404 EMPLOYEE_NOT_FOUND` otherwise) and the prediction is persisted against it; when omitted, this is an ad-hoc "enter a hypothetical profile" prediction and nothing is persisted.

```json
{
  "age": 35,
  "distance_from_home": 5,
  "monthly_income": 5000.0,
  "percent_salary_hike": 15.0,
  "total_working_years": 10,
  "years_at_company": 5,
  "years_since_last_promotion": 1,
  "years_with_curr_manager": 3,
  "job_level": 2,
  "job_satisfaction": 3,
  "environment_satisfaction": 3,
  "relationship_satisfaction": 3,
  "performance_rating": 3,
  "stock_option_level": 1,
  "department": "Sales",
  "business_travel": "Travel_Rarely",
  "overtime": true,
  "employee_id": null
}
```

Response (real values from a live call against the shipped model):

```json
{
  "employee_id": null,
  "prediction_id": null,
  "probability": 0.2461,
  "flagged": true,
  "decision_threshold": 0.2005,
  "calibration_method": "sigmoid",
  "model_family": "Logistic Regression",
  "imbalance_strategy": "SMOTE",
  "model_version": "1",
  "top_factors": [
    { "feature": "overtime", "contribution": 0.83 },
    { "feature": "business_travel_Travel_Rarely", "contribution": -0.31 }
  ],
  "risk_level": "medium",
  "risk_level_status": "resolved: risk_level is a frozen, ranking-derived tier (owner decision, 2026-08-30) built from the validated four-seed calibrated out-of-fold probability distribution - not the original PRD F9.7 fixed absolute-probability bands, and not a live percentile rank against the current employees table. See GET /attrition/model-info for the exact cutoffs and derivation, and docs/EVALUATION.md's Phase 10 calibration amendment for the underlying evidence.",
  "calibration_known_limitation": "The highest calibration bin under-predicts actual risk by roughly 12-15 percentage points (multi-seed confirmed, Memory.md decision 70) - the calibrated probability for the highest-risk employees is a conservative floor, not an exact figure."
}
```

`risk_level` is computed independently of `flagged`/`decision_threshold` — `flagged` uses `0.2005`, `risk_level` uses the frozen tier cutoffs (`0.3671` High / `0.2270` Medium, see `model-info` below). Neither is derived from the other, and neither ever changes based on what else is in the `employees` table or in the same batch request.

`top_factors` is a per-prediction, signed decomposition (coefficient × this employee's own encoded feature value) from the uncalibrated model's coefficients — the same coefficient-magnitude convention `ml/attrition/metrics.json`'s global `feature_importances` already uses, evaluated per-row instead of globally. It is not SHAP (deferred, Memory.md decision 63) and is never used to compute `probability`.

A missing required feature returns 400, naming exactly which field(s):

```json
{
  "error": {
    "code": "INVALID_FEATURE_SET",
    "message": "Missing required attrition feature(s): monthly_income.",
    "details": { "missing_features": ["monthly_income"] }
  }
}
```

### `POST /attrition/predict/batch` — auth required

Body: `{ "records": [ <same shape as POST /attrition/predict, minus the top-level employee_id nesting — it's a field on each record> ] }`, 1–500 records. One partial failure never destroys the batch (Rules.md 5.1) — each record is predicted and, if `employee_id` is set, persisted independently; a record's own `INVALID_FEATURE_SET` or `EMPLOYEE_NOT_FOUND` marks only that record `failed` and does not affect the others. A missing model artifact, by contrast, fails the whole call (503 `ATTRITION_MODEL_MISSING`) — checked once, up front.

```json
{
  "total": 3,
  "succeeded": 2,
  "failed": 1,
  "results": [
    { "index": 0, "employee_id": 1, "status": "predicted", "prediction": { "...": "AttritionPredictResponse shape above" } },
    { "index": 1, "employee_id": null, "status": "failed", "prediction": null, "code": "INVALID_FEATURE_SET", "reason": "Missing required attrition feature(s): department." },
    { "index": 2, "employee_id": null, "status": "predicted", "prediction": { "...": "..." } }
  ]
}
```

### `GET /attrition/employees` — auth required

Paginated (`?page=&page_size=`, `Page[EmployeeOut]` shape — see "System" above for the envelope). Each employee carries its own 17 business features plus `latest_prediction` (the most recent persisted `AttritionPrediction` for that employee, by `prediction_date`, or `null` if none exists yet):

```json
{
  "items": [
    {
      "id": 1,
      "age": 35,
      "department": "Sales",
      "...": "the remaining 15 business features",
      "latest_prediction": {
        "probability": 0.2461,
        "risk_level": "medium",
        "model_version": "1",
        "prediction_date": "2026-08-30T22:03:00Z"
      }
    }
  ],
  "total": 1470,
  "page": 1,
  "page_size": 20,
  "pages": 74
}
```

### `GET /attrition/model-info` — auth required

```json
{
  "model_family": "Logistic Regression",
  "imbalance_strategy": "SMOTE",
  "calibration_method": "sigmoid",
  "calibrated_decision_threshold": 0.2005,
  "model_version": "1",
  "feature_names": ["age", "distance_from_home", "...", "overtime"],
  "raw_evaluation_threshold": 0.55,
  "raw_evaluation_metrics": { "accuracy": 0.765, "precision": 0.369, "recall": 0.660, "f1": 0.473, "roc_auc": 0.784 },
  "calibrated_evaluation_metrics": { "brier_score": 0.103, "recall": 0.6596, "f1": 0.4769, "...": "sealed test set, threshold 0.2005" },
  "calibration_brier_improvement_mean": 0.0629,
  "calibration_brier_improvement_std": 0.0015,
  "calibration_known_limitation": "The highest calibration bin under-predicts actual risk by roughly 12-15 percentage points...",
  "risk_band_status": "resolved",
  "risk_band_note": "resolved: risk_level is a frozen, ranking-derived tier (owner decision, 2026-08-30)...",
  "risk_tier_scheme": "top10_high_next15_medium",
  "risk_tier_high_cutoff": 0.3671,
  "risk_tier_medium_cutoff": 0.2270,
  "risk_tier_percentile_method": "Per-seed p90 (High) / p75 (Medium) computed independently on each seed's own calibrated out-of-fold probability array, then averaged across seeds...",
  "risk_tier_oof_seeds": [42, 43, 44, 45],
  "risk_tier_oof_population": 1176,
  "risk_tier_derivation_date": "2026-08-30",
  "risk_tier_known_limitation": "The sigmoid calibration's highest decile under-predicts actual risk by roughly 12-15 percentage points..."
}
```

`raw_evaluation_metrics` is `ml/attrition/04_evaluate.py`'s sealed-test result at the uncalibrated `0.550` cutoff (Phase 10). `calibrated_evaluation_metrics` is the calibrated model's own sealed-test result at `0.2005` (`ml/attrition/09_finalize_calibrated_model.py`). Both are shown, clearly separated, rather than picking one.

`risk_tier_*` fields are the full derivation record for `risk_level`'s frozen cutoffs (`ml/attrition/12_finalize_risk_tier.py`) — a consumer or auditor can see exactly which OOF population, seeds, percentiles, and date produced the two cutoffs without reading `decision_threshold.json` directly. These cutoffs are never equal to `calibrated_decision_threshold` (`0.2005`) — the binary flag and the display tier are deliberately independent numbers answering different questions.

---

## Analytics (Phase 12, PRD F10)

All four routes require auth and accept the same two filters: `?job_id=` and `?from=&to=` (inclusive date range, `YYYY-MM-DD`). `from` after `to` is rejected with **400**. Every returned number is a SQL `GROUP BY`/`COUNT`/`AVG` result — never a full table fetched into Python and aggregated there (Phases.md Phase 12 acceptance) — and every response echoes the filters it was actually computed under in a `filters` object, so a caller never has to guess which `job_id`/date range a given set of numbers reflects.

Measured against 500 seeded candidates / 150 seeded employees on a live server (not `TestClient` in-process — see `Memory.md`): all four endpoints responded in 12–19 ms, well under the 1.5 s target.

### `GET /analytics/overview` — auth required

F10.1 — current `applications.status` distribution matching the filters (a snapshot of where every application sits today; `applications` has no status-history table, so this is not a cumulative "ever reached this stage" funnel):

```json
{
  "filters": { "job_id": 4, "date_from": null, "date_to": null },
  "funnel": { "total": 137, "new": 40, "shortlisted": 35, "interviewed": 30, "selected": 20, "rejected": 12 }
}
```

### `GET /analytics/skills` — auth required

F10.2 — most common candidate skills (from `candidate_skills`) and most frequently missing skills across the pipeline (from `candidate_scores.missing_skills`, a JSON array column — unnested in SQL via SQLite's `json_each`/PostgreSQL's `json_array_elements_text`, dialect-branched the same way `database.py` already branches on the SQLite foreign-key pragma). Top 10 of each, ordered by count descending then name ascending for a deterministic tie-break:

```json
{
  "filters": { "job_id": 4, "date_from": null, "date_to": null },
  "top_candidate_skills": [{ "skill_name": "Python", "count": 118 }, { "skill_name": "SQL", "count": 96 }],
  "top_missing_skills": [{ "skill_name": "Kubernetes", "count": 41 }, { "skill_name": "FastAPI", "count": 29 }]
}
```

### `GET /analytics/scores` — auth required

F10.3 — average fit score per job and a 10-bucket (0–10, 10–20, ..., 90–100) score distribution histogram, both computed by the database (a SQL `CASE`/integer-cast bucket expression, not a Python bucketing loop). `overall_average_fit_score` is `null`, not `0.0`, when there is no data yet — same "unknown is not zero" convention as `CandidateScoreResponse`:

```json
{
  "filters": { "job_id": null, "date_from": null, "date_to": null },
  "overall_average_fit_score": 68.4,
  "average_by_job": [
    { "job_id": 4, "job_title": "Machine Learning Engineer", "average_fit_score": 71.2, "candidate_count": 137 }
  ],
  "distribution": [
    { "range_start": 0, "range_end": 10, "count": 0 },
    { "range_start": 60, "range_end": 70, "count": 41 },
    { "range_start": 90, "range_end": 100, "count": 12 }
  ]
}
```

### `GET /analytics/attrition` — auth required

F10.4 — count by risk tier and average probability by department, aggregated directly from the persisted `attrition_predictions.risk_level`/`probability` columns (Phases.md Phase 12: never re-invoke `predictor.py` per employee just to total up already-computed tiers — F9.7's tiers are frozen cutoffs, not a live computation). Only each employee's own latest prediction (within the date range, if given) counts toward every number here.

`job_id` is accepted, for contract consistency with the other three analytics endpoints, but has no effect: employees carry no relationship to jobs anywhere in the schema (Architecture.md 5.1 — attrition is a wholly separate subgraph from jobs/candidates/applications). `job_id_filter_applied` says explicitly whether one was supplied, rather than silently ignoring it. This is a documented interpretation flagged for the project owner's review, not a silent reinterpretation of the contract — see `Memory.md`.

```json
{
  "filters": { "job_id": null, "date_from": null, "date_to": null },
  "job_id_filter_applied": false,
  "total_employees_with_prediction": 150,
  "by_risk_level": [
    { "risk_level": "low", "count": 37 },
    { "risk_level": "medium", "count": 18 },
    { "risk_level": "high", "count": 95 }
  ],
  "by_department": [
    { "department": "Sales", "average_probability": 0.4619, "employee_count": 57 }
  ]
}
```

---

## Export (Phase 12, PRD F13)

### `GET /jobs/{id}/export/csv` — auth required

Accepts the exact same filter/sort query parameters as `GET /candidates` (`search`, `min_score`, `max_score`, `skills`, `min_experience`, `education_level`, `status`, `sort_by`, `sort_order`) minus `job_id` (fixed by the path) and `page`/`page_size` — an export is the complete filtered/sorted result set, never paginated. Both routes call the identical query builder (`candidate_service.build_candidate_query`), so the two can never silently drift apart: the same filters produce the same candidate set in the same order on both routes.

Returns `text/csv` with a `Content-Disposition: attachment` header. Columns: `candidate_id, name, email, fit_score, resume_match_score, skill_match_score, experience_score, education_score, missing_skills, status` (`missing_skills` is `; `-joined). An empty result is a header-only CSV (one line), not an error.

PDF shortlist (F13.3) is optional, lowest-priority scope and was **not built this phase** — deferred, not silently dropped; see `Memory.md`.

---

## Status codes in use

| Code | Meaning |
|---|---|
| 200 | Successful read, update, or delete |
| 201 | Resource created |
| 400 | A `ValidationError`-raised business rule (e.g. `NO_FILES_PROVIDED`, `BATCH_LIMIT_EXCEEDED`, `JOB_HAS_NO_SKILLS`, `INVALID_FEATURE_SET`, `INVALID_CANDIDATE_COUNT`) |
| 401 | Missing or invalid token |
| 403 | Authenticated but not permitted (admin-only actions) |
| 404 | Resource does not exist (including `EMPLOYEE_NOT_FOUND`) |
| 409 | Conflict (duplicate email) |
| 422 | Pydantic validation failure, including an unknown/forbidden field or a business-rule violation raised as a validation error |
| 500 | Unhandled server error (`INTERNAL_ERROR`, with a correlation id) |
| 503 | A required model or provider is unavailable (`EMBEDDING_MODEL_UNAVAILABLE`, `LLM_UNAVAILABLE`, `LLM_TIMEOUT`, `LLM_INVALID_OUTPUT`, `INSUFFICIENT_GROUNDED_QUESTIONS`, `ATTRITION_MODEL_MISSING`) |
| 503 | Database unreachable, or `EMBEDDING_MODEL_UNAVAILABLE` (`POST /jobs/{id}/score` with `SCORING_METHOD=embedding` and the model failed to load — every other endpoint, including `SCORING_METHOD=tfidf` scoring, stays healthy) |
