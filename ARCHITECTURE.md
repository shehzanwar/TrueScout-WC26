# TrueScout — Technical Spec / Architecture

> Lives in the repo so we don't rewrite the code halfway through because we picked the wrong database
> or model. Pairs with [`PRD.md`](PRD.md) (the *what*) and [`BOARD.md`](BOARD.md) (the *when*).
>
> **Scope:** V1 — Knockout Stage Intelligence Dashboard · **Last updated:** 2026-06-30

---

## 1. Tech Stack
| Layer | Choice | Notes |
|---|---|---|
| **Frontend** | Next.js (React) + Tailwind CSS + Framer Motion | Dark-mode, animated dashboard. SSR for fast first paint. |
| **Charts** | Lightweight lib (Recharts / Nivo / Observable Plot) | Percentile radars + Knockout Tree. Custom D3 "pizza charts" deferred to post-V1. |
| **Backend** | Python (FastAPI) | Serves models + API; runs `curl_cffi` ingestion and the nightly batch. |
| **Modeling** | PyMC *or* NumPyro (Bayesian) · NumPy (Monte Carlo) · scikit-learn (K-Means, Elastic Net) | No RAPM / Dixon-Coles in V1. |
| **Database** | DuckDB (in-process OLAP) over Parquet cache files | Single file-based store. **PostgreSQL deferred** — unneeded for a single-user batch app. |
| **Ingestion** | `understatapi` (club xG/xA priors) · `soccerdata` (Club Elo) · `curl_cffi` (Sofascore) · `httpx`/`requests` (ESPN) | FBref removed Jan 2026 (Opta data blackout) |
| **Orchestration** | Nightly scheduled job (Windows Task Scheduler / cron / APScheduler) | Runs ETL → re-model → re-sim → Brier log. |
| **LLM** | OpenRouter API (free model, currently `google/gemma-4-31b-it:free`) behind a thin RAG retriever + prompt layer | Model-agnostic; swappable without code changes via `OPENROUTER_MODEL` env var. Reports are pre-generated nightly for high-confidence players (`etl/models/generate_narratives.py`) and served as static JSON; live generation is a fallback only. |
| **Hosting** | FastAPI on Render/Railway/Fly (or self-host) · Next.js on Vercel | DuckDB is file-based → backend stays on a single host. |

---

## 2. Data Model
Rough table sketch (DuckDB tables backed by Parquet). Arrows show foreign-key relations.

```
leagues (id PK, name, elo_strength_coef)
   ▲
teams (id PK, name, league_id → leagues.id)
   ▲
players (id PK, name, team_id → teams.id, position)
   ▲                         │
squads (player_id → players.id, team_id → teams.id, tournament)
   │
   ├─ club_priors (player_id → players.id, season_window, <2-yr aggregated features…>)
   ├─ archetypes (player_id → players.id, kmeans_cluster, silhouette)
   ├─ player_ratings (player_id → players.id, posterior_mean, hdi_low, hdi_high, confidence_score)
   └─ player_match_stats (player_id → players.id, match_id → matches.id, <stats…>)

matches (id PK, round, home_team_id → teams.id, away_team_id → teams.id, result, market_probs)
   │
   └─ brier_log (round, match_id → matches.id, model_prob, market_prob, outcome, brier)

simulations (run_date, round, team_id → teams.id, advance_prob, title_prob)
```

**Key relationships**
- A `player` belongs to one `team`; a `team` belongs to one `league` (which carries the
  `elo_strength_coef` used to scale priors).
- `club_priors` (the Bayesian prior) and `player_match_stats` (the WC likelihood) both feed
  `player_ratings`.
- `archetypes` scopes percentile/Z-score calculations so a defender isn't judged on attacking output.
- `simulations` is rewritten each nightly run; `brier_log` is append-only for tracking over time.

**Static override / supplementary files** (not DuckDB tables — flat JSON under `data/static/`,
applied during ETL or read directly by the frontend):
- `position_overrides.json` — manual corrections for known-corrupted Reep `position_detail` values
  (e.g. Ronaldo mislabeled "Full Back"); applied as a `UPDATE identity_players` in
  `etl/load/load_identity.py` after the Bronze load. Discoverable via `etl/audits/audit_player_data.py`.
- `venues_2026.json` — 16 host-venue coordinates for the World Cup; backs the rest/travel strength
  adjustment in `monte_carlo_sim.py` (currently rest-days only; haversine travel distance not yet wired in).
- `etl/utils/team_aliases.py` (+ `frontend/lib/teamAliases.ts` mirror) — canonical team-name mapping
  shared across the Monte Carlo sim, export pipeline, and audit script so "Türkiye"/"Turkey",
  "USA"/"United States" etc. never silently desync between Sofascore/ESPN/Reep sources.
- `frontend/public/data/narratives/{reep_id}.json` — pre-generated AI scouting reports
  (`{narrative, voice, generated_at}`), written nightly by `etl/models/generate_narratives.py` and
  committed to git like the rest of `public/data/`. `national_team` (modal Sofascore lineup team,
  distinct from Reep's bio `nationality`) is computed in `export_json.py` and embedded directly in
  `players.json` rather than stored as a separate table.

---

## 3. Third-Party APIs
| Service | Use | Access strategy |
|---|---|---|
| **Sofascore v1** | Completed-match stats, lineups, incidents | `curl_cffi` to spoof browser TLS (avoids `403`); primary host **`www.sofascore.com/api/v1`** (same-origin as `Referer`/`Origin` headers — `api.sofascore.com` triggers Cloudflare fake-404); fallback `api.sofascore.app`; integer-ID resolution chain (scheduled-events → `eventId` → lineups/statistics → `teamId`/`playerId`). |
| **ESPN public** | Structural/scoreboard data + betting odds (Brier baseline) | `site.api.espn.com` (slug `soccer/fifa.world`) and `sports.core.api.espn.com`; bundle with `?enable=…`; JSON schema validation (undocumented, unstable). |
| **Club Elo** (via `soccerdata`) | League-strength coefficient | Pulled once; 5-row parquet `league_elo_2026-06-10.parquet`. |
| **Understat** (via `understatapi`) | 2-yr club xG/xA priors (EPL, La_Liga, Bundesliga, Serie_A, Ligue_1) | Replaces FBref. Opta/Stats Perform pulled all advanced metrics from FBref in Jan 2026 under a FIFA betting-data deal; `understatapi` wraps Understat's free xG/xA AJAX endpoint with no auth required. |
| **OpenRouter** | LLM "Tactical Storytelling" | Free model; API key in `.env`; RAG layer is model-agnostic. |

> **Batch, not live.** All scraping happens in the end-of-day job. A failed fetch is retried the next
> night rather than breaking a live feature — this is the core mitigation for fragile/undocumented
> endpoints.

---

## 4. Security / Auth
- **Single-user V1 — no login.** No user accounts, sessions, or PII to protect.
- **Secrets** (OpenRouter key, any tokens) live in `.env`, git-ignored; never committed.
- **Defensive ingestion:** JSON schema validation + try/except on every undocumented endpoint;
  aggressive Parquet caching so a bad night degrades gracefully.
- **Legal/ToS note:** scraping FBref/Sofascore/ESPN/SoFIFA violates their terms; this is treated as a
  **personal-use, rate-limited, cached, non-redistributed** project — not a commercial data product.

---

## 5. Risk Register (verified flaws → mitigations)
| # | Risk | Mitigation in V1 |
|---|---|---|
| 1 | **Pre-tournament scrape window already gone** (today is past kickoff) | Reframed to a **daily end-of-day batch**; completed group stage = initial likelihood; knockouts ingested as they happen. |
| 2 | **Over-scoped** for a solo dev (~12 subsystems) | Keep Bayesian ratings + Monte Carlo; **drop RAPM + Dixon-Coles**; defer WebGL, KNN twins, live firehose. |
| 3 | **Sofascore TLS-spoof = single point of failure + ToS risk** | Batch tolerates failure (retry next night); ESPN fallback; Parquet caching; personal-use/rate-limited. Escalation path if `curl_cffi` fingerprint is defeated: swap `__enter__` + `_fetch_url` for `wreq` (Python, BoringSSL / JA4). |
| 4 | **Tiny WC samples (3–7 matches)** → posterior dominated by priors | Stated honestly: the value is **cross-league prior translation**, not WC likelihood moving the needle; partial pooling shrinks low-minute players. |
| 5 | **Monte Carlo fatigue params unsourced** | Shipped the sim **without** a full fatigue model in V1. A simple, explicitly uncalibrated rest-days penalty (`-0.10 × max(0, 3 - rest_days)`) was added in Phase 4 as a cheap directional signal; the full fatigue model (minutes load + travel distance) stays in `BOARD.md` Backlog pending calibration. |
| 6 | **"Beat the market" oversells** | Reframed as a **Brier-score tracker** vs market odds — a measured comparison, not a guarantee. |
| 7 | **Stale LLM choice** (GPT-4o-mini / Claude 3 Haiku) | **OpenRouter free model**; RAG layer model-agnostic. |
| 8 | **KNN "statistical twins" fabricate missing metrics** | Dropped; a **confidence score** routes sparse players to the no-stats "Traditional Scout" LLM path. |
| 9 | **Dual DB overhead** (Postgres + DuckDB) | **DuckDB + Parquet only** in V1; Postgres deferred. |
| 10 | **FBref data blackout (Jan 2026)** — Opta/Stats Perform pulled xG, xA, progressive carries, pressures from FBref under FIFA betting-data deal | Pivoted to **Understat** (`understatapi`): same StatsBomb event-data feed, no auth, covers EPL/La_Liga/Bundesliga/Serie_A/Ligue_1. Columns without an Understat equivalent (SCA, GCA, pressures, progressive carries) are NULL in Bronze; Phase 2 Bayesian partial pooling handles sparse features gracefully. |
