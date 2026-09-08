# Setup

Local setup from scratch. Two paths: run the backend and frontend directly
(this document, in order below), or use Docker Compose (last section) for
backend + PostgreSQL without installing Python or Node locally. Either path
gets you a running server; only the direct path also gets you a running
frontend dev server today (Phase 16 Stage 1 ships no frontend Compose
service yet).

## Prerequisites

- **Python 3.11** (Rules.md §4.1 — the project does not run on other
  versions; verified against 3.11.9).
- **Node.js 20 or newer** for the frontend (verified against 20.18.0; no
  `engines` field is enforced, but the pinned `vite@^6` toolchain needs a
  reasonably current Node).
- **git**.
- For the Docker Compose path only: **Docker** with the `docker compose`
  v2 CLI (`docker compose version`). Not required for the direct path —
  the backend's default `DATABASE_URL` is SQLite, a plain file, no server
  needed.
- For the attrition model artifacts only: the raw Kaggle CSV — see
  "Attrition model artifacts" below.

## Backend

All commands in this section run from `backend/`.

### 1. Create a virtual environment and install dependencies

```bash
cd backend
python -m venv .venv
```

Activate it — `.venv\Scripts\activate` on Windows (cmd or PowerShell),
`source .venv/bin/activate` on macOS/Linux — then:

```bash
pip install -r requirements.txt
```

This installs everything the running API needs: FastAPI, SQLAlchemy,
Alembic, the ML/NLP stack (spaCy, sentence-transformers, scikit-learn),
`imbalanced-learn` (needed to unpickle the shipped attrition model — see
"Attrition model artifacts" below), and both LLM provider SDKs. It does
**not** install `ml/requirements.txt` — that's a separate, larger,
training-only dependency set (`xgboost`, `shap`, `matplotlib`, `jupyter`),
needed only if you're going to regenerate the attrition model artifacts
yourself (next section), not to run the server.

### 2. Create `.env`

```bash
cp .env.example .env
```

Every value in `.env.example` already has a working development default
(Architecture.md §8) — the server starts and almost every endpoint works
with zero edits. The three keys that ship empty:

| Key | Must you fill it? |
|---|---|
| `SECRET_KEY` | No, for local development — an empty key only logs a startup warning when `APP_ENV=development` (the default). It must be a real random value before `APP_ENV` is ever `staging` or `production`; the server refuses to start otherwise. |
| `OPENAI_API_KEY` | Only if you want `POST /candidates/{id}/interview-questions` to actually succeed. `LLM_MODEL`/`OPENAI_BASE_URL` already point at a working Groq-hosted model by default (see the comments in `.env.example`); without a key, the server still starts fine and every other endpoint works — that one endpoint returns a `503`/`LLM_UNAVAILABLE` at request time, not at startup. |
| `ANTHROPIC_API_KEY` | Only if you change `LLM_PROVIDER` to `anthropic`. Unused otherwise. |

`DATABASE_URL` defaults to `sqlite:///./hiring.db` — a file created next
to this document's commands, no separate database server needed.

### 3. Run migrations

```bash
alembic upgrade head
```

Creates `hiring.db` (or whatever `DATABASE_URL` points at) with every
table the app needs, from empty.

### 4. Start the server

```bash
uvicorn app.main:app --reload
```

Verify: `curl http://localhost:8000/api/v1/health` should return
`{"status":"healthy",...,"database":"connected"}`. The startup log will
also show a line like `Attrition model unavailable at startup` — expected
at this point (next section) and harmless; every non-attrition endpoint is
already fully working.

## Attrition model artifacts

`ml/attrition/artifacts/*.joblib` is gitignored (Phases.md Phase 0) — a
fresh clone has no trained attrition model on disk. **Until all three
commands below have been run, in order, `/attrition/predict`,
`/attrition/predict/batch`, `/attrition/employees`, and
`/attrition/model-info` all return `503 ATTRITION_MODEL_MISSING`.** This
is not a bug and not a partial failure — every other endpoint is
unaffected, both before and after you run these, per `app/ml/attrition/predictor.py`.

First, install the extra training-only dependencies (into the same venv
as the backend, or a separate one — either works):

```bash
pip install -r ../ml/requirements.txt
```

Then obtain `data/raw/WA_Fn-UseC_-HR-Employee-Attrition.csv` — see
`data/README.md` for the exact Kaggle source and licence terms. Then, from
the repository root (these scripts resolve their own paths from their own
file location, not from your current directory, but running from root
matches how they're written and tested):

```bash
python ml/attrition/03_train.py
python ml/attrition/09_finalize_calibrated_model.py
python ml/attrition/12_finalize_risk_tier.py
```

`03_train.py` fits and saves `model.joblib`, `preprocessor.joblib`,
`feature_names.json`, and `decision_threshold.json`'s base threshold.
`09_finalize_calibrated_model.py` persists the calibrated serving model
(`calibrated_model.joblib`) and re-derives its own recommended threshold,
asserting it matches the already-validated value before writing anything.
`12_finalize_risk_tier.py` does the same for the risk-tier cutoffs. All
three must succeed, in order — running only `03_train.py` leaves
`calibrated_model.joblib` and the other two sections of
`decision_threshold.json` missing, which `predictor.load_artifacts()`
still treats as `ATTRITION_MODEL_MISSING`. `python ml/attrition/04_evaluate.py`
is optional — it only re-confirms `03_train.py`'s sealed-test numbers into
`metrics.json` and isn't required for serving.

Restart the server (or just wait for `--reload` to pick up nothing — the
artifacts are read once at startup, so restart uvicorn) and re-check
`/attrition/model-info`; it should now return real values instead of a
`503`.

## Frontend

All commands in this section run from `frontend/`.

```bash
cd frontend
npm install
cp .env.example .env
```

`.env.example` contains one key, already correct for local development
against the backend steps above:

```
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

Development server (hot reload, default port 5173 — matches the
backend's default `CORS_ORIGINS`):

```bash
npm run dev
```

Production build (type-checks first, then bundles to `frontend/dist/`):

```bash
npm run build
```

## Docker Compose (alternative to the backend section above)

Runs the backend and PostgreSQL 16 in containers — no local Python
install needed for this path. From the repository root:

```bash
docker compose up
```

Every value `docker-compose.yml` needs has a working default baked in —
no `.env` file is required for the stack to come up and `GET /health` to
report healthy. `db` (Postgres) starts, a one-shot `migrate` service runs
`alembic upgrade head` against it and must exit successfully before
`backend` starts at all, then `backend` serves on `http://localhost:8000`.
To supply real secrets (an `OPENAI_API_KEY`, a non-default Postgres
password), create a `.env` file next to `docker-compose.yml` — Compose
loads it automatically — or export the variables in your shell first.

The attrition model artifacts are **not** baked into the image (see
"Attrition model artifacts" above — same reasoning applies: gitignored,
and the training pipeline's dependencies don't belong in a serving image).
If you've already run the three scripts above on your host,
`docker-compose.yml` mounts `./ml/attrition/artifacts` read-only into the
container at the exact path the app expects, so they're picked up
automatically. Otherwise, the attrition endpoints return the same
`503 ATTRITION_MODEL_MISSING` as the direct path.

This path is verified through a clean-checkout GitHub Actions run
(`.github/workflows/docker.yml`), not locally on every contributor's
machine — see `Memory.md` for why local Docker verification on this
project's own dev machine is closed as WON'T FIX and what that CI run
actually checked (image build, Postgres health, the real migration,
backend health, `imblearn` importability, and the documented
model-missing path over real HTTP).
