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
  runs daily at 02:00 UTC:
    1. ESPN pull → Bronze Parquet
    2. Sofascore pull → Bronze Parquet
    3. Load group-stage results
    4. Build feature matrix
    5. Bayesian ratings
    6. Monte Carlo bracket sim
    7. Brier tracker
    8. etl/export_json.py → frontend/public/data/*.json

Vercel
  auto-deploys on every push to master
  serves the Next.js app + static JSON via CDN
  Next.js API route /api/narratives/[reep_id] → OpenRouter (server-side)
```

Data flow on a page request:
- Server Components (page.tsx) read JSON from disk via `lib/server-data.ts`
- Client Components download `/data/players.json` once and cache it (player search)
- "Generate Report" button calls `/api/narratives/[reep_id]` (same-origin, no CORS)

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
| `OPENROUTER_API_KEY` | [openrouter.ai/keys](https://openrouter.ai/keys) | Yes (for narratives) |
| `OPENROUTER_MODEL` | e.g. `meta-llama/llama-3.1-8b-instruct:free` | No (has default) |

Add these under **Project Settings → Environment Variables**.

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

# Frontend
cd frontend
npm install
npm run dev          # http://localhost:3000
```

For the narrative API route to work locally, create `frontend/.env.local`:
```
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=meta-llama/llama-3.1-8b-instruct:free
```

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
