# TrueScout — Deployment Guide

**Architecture**: Static JSON files (GitHub repo) + Next.js (Vercel) + nightly GitHub Actions pipeline.
No Docker, no paid cloud servers.

---

## How it works

```
GitHub repo
  └─ frontend/public/data/*.json   ← generated nightly by ETL pipeline
       ▲
       │  git push  [skip ci]
       │
GitHub Actions (.github/workflows/nightly.yml)
  runs daily at 02:00 UTC (run_nightly.py, 9 steps):
    1. ESPN pull (knockout) → Bronze Parquet
    2. Sofascore pull (all rounds) → Bronze Parquet
    3. Load matches (group stage + knockout)
    4. Load identity crosswalk (Reep) — applies data/static/position_overrides.json
    5. Build Silver feature matrix
    6. Bayesian ratings update
    7. Monte Carlo bracket sim — includes rest/travel strength penalty (PR5b.1)
    8. Brier score tracker
    9. etl/export_json.py → frontend/public/data/*.json
   9.5. etl/verify_outputs.py → hard assertions on exported JSON (hard-fail gate)

Vercel
  auto-deploys on every push to master
  serves the Next.js app + static JSON via CDN
  Next.js API route /api/narratives/[reep_id] → Gemini 2.5 Flash (server-side, GOOGLE_AI_API_KEY)
```

Data flow on a page request:
- Server Components (page.tsx) read JSON from disk via `lib/server-data.ts`
- Client Components download `/data/players.json` once and cache it (player search, `/compare`)
- `TacticalAnalysis.tsx` shows a "Generate Scouting Report" button → clicks call
  `/api/narratives/[reep_id]` (Next.js API route, same-origin, no CORS) → OpenRouter

---

## First-time Vercel setup

### 1 — Import the repo

1. Push this repo to GitHub (any visibility).
2. Go to [vercel.com](https://vercel.com) → **Add New Project** → Import the repo.
3. Set **Framework Preset**: `Next.js`
4. Set **Root Directory**: `frontend`
5. Click **Deploy** — the placeholder JSONs deploy fine on first run.

### 2 — Set environment variables in Vercel

| Variable | Where to get it | Required? |
|---|---|---|
| `GOOGLE_AI_API_KEY` | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | Yes (for "Generate Report" calls — Gemini 2.5 Flash) |
| `OPENROUTER_API_KEY` | [openrouter.ai/keys](https://openrouter.ai/keys) | No (legacy; kept for config.py compat) |
| `OPENROUTER_MODEL` | e.g. `poolside/laguna-m.1:free` | No |

Add these under **Project Settings → Environment Variables**.

> **AI route notes:**
> - Uses Gemini 2.5 Flash (`gemini-2.5-flash`) via native REST — no OpenRouter dependency for narratives.
> - `export const maxDuration = 60` on Vercel Pro only. On Hobby (10s cap) the call may timeout for slow responses.
> - The route strips `<think>…</think>` reasoning preambles from model output automatically.
> - On failure the route returns HTTP 502 with `{ error: "<reason>" }` — check Vercel function logs if users report errors.
> - Nightly pre-gen (step 9.6 in `run_nightly.py`) runs but hits Gemini 503 quota after ~6 players; on-demand via UI button is the active path.

### 3 — Enable GitHub Actions

1. In the GitHub repo → **Settings → Actions → General** → ensure "Allow all actions" is on.
2. The `GITHUB_TOKEN` secret is auto-provisioned — no manual setup needed.
3. To trigger the first real data run: go to **Actions → Nightly ETL + Static Export → Run workflow**.

After it succeeds, Vercel will auto-deploy with real data.

---

## Local development

```bash
# Backend (optional — only needed if you want to test FastAPI locally)
pip install -r requirements.txt
uvicorn main:app --reload --port 8001

# Run the ETL pipeline once to populate local data
python run_nightly.py
python etl/export_json.py

# Optional — pre-generate AI scouting reports for the top players
# (requires OPENROUTER_API_KEY in your shell env)
python -m etl.models.generate_narratives --limit 50

# Frontend
cd frontend
npm install
npm run dev          # http://localhost:3000
```

For the narrative API route to work locally, `frontend/.env.local` needs:
```
NEXT_PUBLIC_API_URL=http://localhost:8001/api/v1
GOOGLE_AI_API_KEY=...      # from aistudio.google.com/apikey
OPENROUTER_API_KEY=...     # legacy; kept for config.py compat
```

For narrative pre-gen from the Python pipeline, the project root `.env` also needs `GOOGLE_AI_API_KEY`.
`run_nightly.py` and `generate_narratives.py` both load it via `python-dotenv` automatically.

---

## Nightly pipeline failure modes

The `run_nightly.py` orchestrator has per-step `try/except` with soft-fail, so a
single failed scrape (e.g. Sofascore Cloudflare block) does not abort the run.
The export step writes whatever data is currently in DuckDB.

To inspect failures, check the **Actions** tab in GitHub.

---

## Updating data manually

```bash
# From your local machine (with a populated DuckDB):
python etl/export_json.py
git add frontend/public/data/
git commit -m "chore: manual data refresh"
git push
```

Vercel redeploys automatically within ~30 seconds.
