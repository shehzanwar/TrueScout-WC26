
<div align="center">

# ⚽ TrueScout — WC 2026 Intelligence

### A knockout-stage intelligence dashboard for the 2026 FIFA World Cup

Hierarchical Bayesian player ratings · 100,000-run Monte Carlo bracket simulation · Brier-score calibration tracking · confidence-gated RAG tactical narratives

[![Live Demo](https://img.shields.io/badge/Live_Demo-truescout.vercel.app-000?logo=vercel&logoColor=white)](https://truescout.vercel.app)
[![Next.js](https://img.shields.io/badge/Next.js-16-black?logo=next.js&logoColor=white)](https://nextjs.org)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![Vercel](https://img.shields.io/badge/Deployed_on-Vercel-000)](https://vercel.com)
[![GitHub Actions](https://img.shields.io/badge/Pipeline-GitHub_Actions-2088FF?logo=githubactions&logoColor=white)](https://github.com/features/actions)

</div>

---

## 📖 Overview

**TrueScout** is a self-running, data-driven intelligence dashboard for the **2026 FIFA World Cup knockout stage**. It answers two questions that ordinary stats cannot:

1. **"How good is this player *really*?"** — raw numbers lie because a 20-goal season in a weak league is not the same as 20 goals in a top-5 European league. TrueScout translates two years of club form into a single, league-adjusted, position-scoped rating using a **hierarchical Bayesian model**, then updates it with World Cup minutes as fresh evidence.
2. **"Who's actually going to win?"** — it re-simulates the **remaining bracket 100,000 times** every matchday to produce calibrated title and advancement probabilities, and grades itself against the betting market with a running **Brier score**.

Every night, an automated pipeline pulls the day's results, refreshes the ratings, re-runs the simulation, and republishes the dashboard — no manual intervention required.

> **Live site:** [truescout.vercel.app](https://truescout.vercel.app)
> **Repository:** [github.com/shehzanwar/TrueScout-WC26](https://github.com/shehzanwar/TrueScout-WC26)

---

## ✨ Key Features

### 🎯 League-adjusted player ratings
A **hierarchical Bayesian model** uses two years of club-season data as the *prior*, scaled by a league-strength coefficient (Club Elo), and treats World Cup minutes as the *likelihood*. **Partial pooling** shrinks low-minute players toward their archetype average so a single good game can't inflate a rating. Final scores are expressed as **percentiles within position and archetype** — a centre-back is judged on defending, a winger on creating, never the same yardstick.

### 🌳 Monte Carlo bracket simulation
The remaining knockout bracket is simulated **100,000 times** every matchday, producing per-team advancement and title probabilities. The result is an interactive **Knockout Tree** that updates the moment each round completes. A lightweight rest-days strength adjustment (`-0.10 × max(0, 3 - rest_days)`) adds a directional fatigue signal.

### 📊 Brier-score calibration tracker
Instead of claiming to "beat the market," TrueScout logs a **Brier score** against betting-market odds after every round — an honest, measured calibration check. The dashboard surfaces graded matches, the running Brier score, and the edge versus a coin-flip baseline.

### 📝 Confidence-gated tactical narratives
A RAG "Tactical Storytelling" layer generates a scouting report on demand for any player. It is **role-aware**: high-confidence players get a metrics-driven **"Data Analyst"** voice, while sparse-data players are routed to a **"Traditional Scout"** voice that is explicitly forbidden from inventing statistics. Narratives run through **Gemini 2.5 Flash** with an OpenRouter fallback chain.

### 🏠 Insight-driven home page
The landing surface surfaces the four things a fan wants first — **Title Favorites**, **Next Match** with win probabilities, a **Value Pick** card highlighting the biggest model-vs-bookies gap, and the **Top Performers** leaderboard.

### ⚖️ Side-by-side player comparison
A dedicated `/compare` view puts any two players head-to-head on ratings and attributes, returning a plain-English verdict on who comes out ahead and why.

---

## 🧱 Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| **Frontend** | Next.js 16 (React 19) + Tailwind CSS 4 + Framer Motion + Recharts | Dark-mode, animated, SSR dashboard. |
| **Backend** | Python · FastAPI | Serves models and the optional API; runs ingestion and the nightly batch. |
| **Modeling** | NumPy (Bayesian + Monte Carlo) · scikit-learn (K-Means archetypes, Elastic Net) | The Bayesian model is **pure NumPy** — no PyMC/NumPyro dependency. |
| **Database** | DuckDB (in-process OLAP) over Parquet | Single file-based store; no Postgres in V1. |
| **Ingestion** | `curl_cffi` (Sofascore, TLS-spoofed) · `httpx`/`requests` (ESPN) · `understatapi` (club xG/xA priors) · `soccerdata` (Club Elo) | Replaces FBref (Opta data blackout, Jan 2026). |
| **LLM** | Gemini 2.5 Flash (native REST) · OpenRouter fallback chain (Laguna M.1 → Gemma 4 31B → Nemotron → Llama 3.3 70B) | On-demand via Next.js API route; reasoning-tag stripping + `maxDuration = 60`. |
| **Orchestration** | GitHub Actions (nightly, 02:00 UTC) | 9-step ETL → re-model → re-sim → Brier → export. |
| **Hosting** | Next.js on Vercel + static JSON committed to the repo | No Docker, no paid cloud servers. |

---

## 🗂️ Project Structure

```text
TrueScout-WC26/
├── frontend/                 # Next.js 16 dashboard (Vercel-deployed)
│   ├── app/                  # App-router pages (knockout tree, matchups, nations, search, compare, calibration)
│   ├── app/api/narratives/   # On-demand LLM scouting-report route
│   ├── public/data/*.json    # Nightly-generated static datasets (served via CDN)
│   └── lib/                  # server-data access + teamAliases mirror
├── api/                      # FastAPI routes (health, players, matchups, simulations, brier, narratives)
├── etl/                      # Bronze → Silver → Gold pipeline
│   ├── db/                   # DuckDB connection + schema bootstrap
│   ├── load/                 # Identity crosswalk, matches, priors
│   ├── models/               # Bayesian ratings, Monte Carlo sim, archetypes
│   ├── audits/               # Data-quality audit scripts
│   └── utils/                # Team-name aliases + shared helpers
├── data/                     # DuckDB file + Parquet (bronze/silver/gold) + static/ JSON
├── .github/workflows/        # nightly.yml — scheduled ETL + export pipeline
├── main.py                   # FastAPI application entry point
├── run_nightly.py            # 9-step nightly orchestrator
├── config.py                 # Pydantic settings (env-driven)
├── check.py                  # Inspect player ratings + prior status from DuckDB
├── requirements.txt          # Python dependencies (pinned for the tournament)
├── PRD.md                    # Lean product spec (the "what")
├── ARCHITECTURE.md           # Technical spec (the "how")
├── DEPLOYMENT.md             # Vercel + GitHub Actions setup
├── BOARD.md                  # Roadmap + backlog (the "when")
└── CONTEXT.md                # Living project context

```

---

## 🔄 How It Works

### The nightly pipeline (`run_nightly.py`)

Every night at **02:00 UTC**, a GitHub Actions workflow runs the full pipeline. Each step is wrapped in `try/except` with soft-fail, so a single blocked scrape (e.g. a Sofascore Cloudflare challenge) never aborts the whole run.

```text
GitHub Actions (nightly.yml)
   │
   1. ESPN pull (knockout)               → Bronze Parquet
   2. Sofascore pull (all rounds)        → Bronze Parquet
   3. Load matches (group stage + knockout)
   4. Load identity crosswalk (Reep)     → applies position_overrides.json
   5. Build Silver feature matrix
   6. Bayesian ratings update
   7. Monte Carlo bracket sim            → rest/travel strength penalty
   8. Brier-score tracker
   9. export_json.py                     → frontend/public/data/*.json
  9.5 verify_outputs.py                  → hard-assertion quality gate
   │
   └─ git push [skip ci]  →  Vercel auto-deploys (~30s)

```

### Request-time data flow

* **Server Components** read JSON from disk via `lib/server-data.ts` for a fast first paint.
* **Client Components** download `/data/players.json` once and cache it (player search, `/compare`).
* The **"Generate Scouting Report"** button calls the same-origin Next.js API route `/api/narratives/[reep_id]`, which streams the player's fact bullets to Gemini 2.5 Flash and returns a cleaned narrative.

---

## 🚀 Getting Started

### Prerequisites

* **Node.js** ≥ 20 and **npm** (for the frontend)
* **Python** ≥ 3.11 (for the backend / ETL pipeline)
* A **Google AI API key** ([aistudio.google.com/apikey](https://aistudio.google.com/apikey)) — required for on-demand scouting reports

### 1. Clone the repository

```bash
git clone [https://github.com/shehzanwar/TrueScout-WC26.git](https://github.com/shehzanwar/TrueScout-WC26.git)
cd TrueScout-WC26

```

### 2. Run the data pipeline (optional — only if you want fresh local data)

```bash
pip install -r requirements.txt
cp .env.example .env          # fill in your API keys
python run_nightly.py         # full ETL + model + sim + export
python etl/export_json.py     # write frontend/public/data/*.json

```

### 3. Start the frontend

```bash
cd frontend
npm install
npm run dev                   # http://localhost:3000

```

The dashboard ships with placeholder JSON, so it runs even before the pipeline has executed.

### 4. (Optional) Run the FastAPI backend locally

```bash
uvicorn main:app --reload --port 8001

```

### Environment variables

Copy `.env.example` → `.env` and configure. The most important ones:

| Variable | Purpose | Required? |
| --- | --- | --- |
| `GOOGLE_AI_API_KEY` | Powers "Generate Scouting Report" (Gemini 2.5 Flash) | **Yes** (for narratives) |
| `OPENROUTER_API_KEY` | Legacy fallback / Python-side narrative pre-gen | No |
| `OPENROUTER_MODEL` | Default OpenRouter model id | No |
| `DUCKDB_PATH` | Location of the DuckDB file | No (has default) |
| `MC_ITERATIONS` | Monte Carlo iterations per run (default `10000`) | No |
| `CONFIDENCE_SCORE_THRESHOLD` | Below this → "Traditional Scout" LLM voice | No |
| `NARRATIVE_CONFIDENCE_THRESHOLD` | Routing threshold for "Data Analyst" voice | No |
| `ALLOWED_ORIGINS` | CORS allow-list (JSON array) | No |

---

## ☁️ Deployment

TrueScout is designed for **zero-cost hosting**: static JSON committed to the repo + a Next.js app on Vercel + a scheduled GitHub Actions runner. Full step-by-step instructions live in [`DEPLOYMENT.md`](https://www.google.com/search?q=DEPLOYMENT.md).

### Vercel (frontend)

1. Import the repo at [vercel.com](https://vercel.com) → **Add New Project**.
2. Set **Framework Preset** → `Next.js`, **Root Directory** → `frontend`.
3. Add `GOOGLE_AI_API_KEY` under **Project Settings → Environment Variables**.
4. Deploy — the placeholder JSONs work on first run.

> **Note:** the narrative route sets `maxDuration = 60`, which requires **Vercel Pro**. On the Hobby tier (10s cap) slow LLM responses may time out; the on-demand UI button remains the active path.

### GitHub Actions (nightly data)

1. In the repo → **Settings → Actions → General**, ensure "Allow all actions" is on.
2. `GITHUB_TOKEN` is auto-provisioned — no manual secret needed.
3. Trigger the first run via **Actions → Nightly ETL + Static Export → Run workflow**.

On success, the workflow commits fresh JSON and Vercel redeploys automatically.

### Manual data refresh

```bash
python etl/export_json.py
git add frontend/public/data/
git commit -m "chore: manual data refresh"
git push                        # Vercel redeploys in ~30s

```

---

## 🔌 Data Sources

| Source | Used for | Access |
| --- | --- | --- |
| **Sofascore v1** | Completed-match stats, lineups, incidents | `curl_cffi` TLS-spoofing (avoids 403/Cloudflare); ESPN fallback |
| **ESPN public API** | Scoreboard structure + betting odds (Brier baseline) | `httpx`/`requests`, JSON schema validation |
| **Understat** (via `understatapi`) | 2-yr club xG/xA priors (top-5 leagues) | Free AJAX endpoint, no auth — replaces FBref |
| **Club Elo** (via `soccerdata`) | League-strength coefficient | Pulled once to Parquet |
| **Google AI / OpenRouter** | Tactical narratives | API key in `.env` |

> **Batch, not live.** All scraping happens in the end-of-day job. A failed fetch is retried the next night rather than breaking a live feature — this is the core mitigation for fragile, undocumented endpoints.

---

## ⚖️ Legal & Usage Notes

* **Personal-use, rate-limited, cached, and non-redistributed.** Scraping Sofascore / ESPN / Understat may violate their terms of service; this project is a personal analytics portfolio piece, **not** a commercial data product.
* **Probabilities are statistical model estimates** — not predictions, guarantees, or betting advice. The Brier tracker is a calibration check, not a claim of beating the market.
* Secrets (API keys) live in `.env`, which is git-ignored and never committed.

---

## 🗺️ Roadmap

A full Phase 5 queue lives in [`BOARD.md`](https://www.google.com/search?q=BOARD.md). Highlights:

* **AI Analyst stabilization** — Vercel `maxDuration = 60`, reasoning-tag stripping, robust fallback model chain.
* **Nightly narrative pre-generation (PR7)** — Python emits structured fact bullets; the LLM only rephrases and can never invent numbers (templated anti-hallucination pattern).
* **"Story of the day" + 80-word match previews** generated each matchday.
* **Untapped data** — discipline posteriors, age cohorts, "who plays like X?" similarity, npxG vs xG finishing decomposition, Golden Boot/Ball Monte Carlo projections.
* **Deferred engine work** — time-aware Bayesian v2, empirical hyperparameter calibration (needs ≥20 graded matches), team-level Bayesian posterior, Dixon-Coles scoreline model.

Explicitly **out of scope** for V1 (parked, not lost): live minute-by-minute firehose, RAPM, KNN "statistical twin" imputation, WebGL/deck.gl pitch rendering, multi-user auth, PostgreSQL, native mobile app.

---

## 📚 Documentation

| Doc | What it covers |
| --- | --- |
| [`PRD.md`](PRD.md) | Product scope, success metrics, user flow, in/out-of-scope |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Tech stack, data model, third-party APIs, risk register |
| [`DEPLOYMENT.md`](https://www.google.com/search?q=DEPLOYMENT.md) | Vercel + GitHub Actions setup, local dev, failure modes |
| [`BOARD.md`](https://www.google.com/search?q=BOARD.md) | Roadmap phases and backlog |
| [`CONTEXT.md`](CONTEXT.md) | Living project context |

---

## 🤝 Contributing

This is a personal portfolio project, but suggestions and issue reports are welcome.

1. Fork the repository and create a feature branch (`feat/your-idea`).
2. Keep changes within the scope defined in [`PRD.md`](PRD.md) — if it isn't in the PRD, it isn't being built yet.
3. Run the audit scripts under `etl/audits/` to catch data-quality regressions.
4. Open a pull request describing the change and linking any relevant issue.

---

## 👤 Author & Acknowledgements

**Shehzad Anwar** — [github.com/shehzanwar](https://github.com/shehzanwar)

Built as a rigorous, self-running analytics portfolio piece for the 2026 FIFA World Cup. Thanks to the maintainers of `understatapi`, `soccerdata`, and `curl_cffi`, and to the open football-analytics community whose public work made the league-strength translation possible.

**[🌐 Live Dashboard](https://truescout.vercel.app)** · **[📦 Source Code](https://github.com/shehzanwar/TrueScout-WC26)**

*Probabilities are statistical estimates — not betting advice.*
