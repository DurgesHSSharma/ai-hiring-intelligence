# API Reference

Generated summary of the actual backend contract. Updated whenever the contract changes (Rules.md §8) — most recently for Phase 6 (scoring and rankings).

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

## Candidates

All routes require auth. No role restriction (F1.5 limits role enforcement to job delete only).

### `GET /candidates` — auth required

Query parameters: `page`, `page_size`. No search/filter/sort yet — that is Phase 12 (PRD F12).

Response — **200**, `Page[CandidateResponse]`:

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
      "created_at": "2026-08-26T18:15:24"
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

## Status codes in use

| Code | Meaning |
|---|---|
| 200 | Successful read, update, or delete |
| 201 | Resource created |
| 400 | A `ValidationError`-raised business rule (e.g. `NO_FILES_PROVIDED`, `BATCH_LIMIT_EXCEEDED`, `JOB_HAS_NO_SKILLS`) |
| 401 | Missing or invalid token |
| 403 | Authenticated but not permitted (admin-only actions) |
| 404 | Resource does not exist |
| 409 | Conflict (duplicate email) |
| 422 | Pydantic validation failure, including an unknown/forbidden field or a business-rule violation raised as a validation error |
| 500 | Unhandled server error (`INTERNAL_ERROR`, with a correlation id) |
| 503 | A required model or provider is unavailable (`EMBEDDING_MODEL_UNAVAILABLE`, `LLM_UNAVAILABLE`, `LLM_TIMEOUT`, `LLM_INVALID_OUTPUT`, `INSUFFICIENT_GROUNDED_QUESTIONS`, `ATTRITION_MODEL_MISSING`) |
| 503 | Database unreachable, or `EMBEDDING_MODEL_UNAVAILABLE` (`POST /jobs/{id}/score` with `SCORING_METHOD=embedding` and the model failed to load — every other endpoint, including `SCORING_METHOD=tfidf` scoring, stays healthy) |
