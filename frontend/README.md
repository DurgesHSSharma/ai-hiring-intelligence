# HireIntel frontend

React 19 + Vite + TypeScript + Tailwind CSS, talking to the FastAPI backend in `../backend`.

## Setup

```bash
npm install
cp .env.example .env   # set VITE_API_BASE_URL if the backend isn't on localhost:8000
npm run dev
```

Requires the backend running (`uvicorn app.main:app --port 8000` from `backend/`) and its `CORS_ORIGINS` to include `http://localhost:5173`.

## Scripts

- `npm run dev` — start the Vite dev server (port 5173)
- `npm run build` — type-check (`tsc -b`) and produce a production build in `dist/`
- `npm run typecheck` — type-check only
- `npm run preview` — preview the production build locally
