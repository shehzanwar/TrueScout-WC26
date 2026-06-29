# TrueScout — Architectural Context & Save Point

> **Purpose:** Single reference for anyone picking up this codebase cold — a new session, a new
> developer, or a debugging session 3 months from now. Covers architecture, math, known landmines,
> and maintenance procedures.
>
> **Last updated:** 2026-06-29 (after Phase 3 complete + CI/CD hardening)

---

## 1. Executive Summary

TrueScout is a serverless, AI-augmented sports analytics engine for the 2026 FIFA World Cup knockout
stage. It runs as a **static dashboard** — all computations happen in a nightly batch job; the
frontend consumes pre-built JSON files served via Vercel CDN.

**Core value proposition:**  
The 48-nation field plays across wildly different leagues. Raw stats are not comparable. TrueScout
solves this through:

1. **Cross-league prior translation via Bayesian shrinkage.** A 2-year club-season prior (xG, xA,
   ratings from Understat, scaled by Club Elo league-strength coefficients) is updated with World Cup
   match data using an analytical Normal-Normal conjugate model. A player's posterior is a
   principled blend of "what they did in their club league" and "what they've shown in this
   tournament." Partial pooling shrinks sparse-WC players toward their archetype cluster mean.

2. **Confidence-gated LLM narratives.** Players with `confidence_score >= 0.7` get a
   metrics-driven "Data Analyst" voice (cites Bayesian numbers directly). Below that threshold,
   a "Traditional Scout" voice is used — which is explicitly forbidden from inventing statistics.
   Routed through OpenRouter (`meta-llama/llama-3.1-8b-instruct:free` by default; swappable).

**Phase status:** All three phases complete. Deployed at https://true-scout.vercel.app/

---

## 2. The "Local Scrape, Cloud Math" Architecture

### Why this pattern exists

Two hard constraints forced this design:

- **Sofascore is permanently blocked on GitHub Actions IPs.** Cloudflare fingerprints datacenter
  TLS handshakes and returns 403. No amount of header spoofing fixes this. The scraper works
  locally because it uses `curl_cffi` to mimic a browser TLS session, which only defeats
  *fingerprint checks*, not *IP reputation blocks*.

- **DuckDB is file-based and single-writer.** You cannot run DuckDB on a Vercel Function or a
  free-tier cloud host that does not persist a filesystem between requests. There is no hosted
  DuckDB — it is an in-process library that reads and writes a `.duckdb` file on disk.

The solution: decouple scraping from computation. The local machine handles everything that needs
a residential IP or a persistent filesystem. GitHub Actions handles the pure math.

### How the flow works

```
┌─────────────────────────┐
│  Developer's Machine    │
│                         │
│  1. sofascore_pull.py   │  ← curl_cffi TLS spoof (residential IP = no 403)
│     espn_pull.py        │  ← httpx (no TLS restriction on ESPN)
│                         │
│  2. Bronze Parquets     │  ← raw data written to data/bronze/**/*.parquet
│     committed to Git    │
│                         │
│  3. git push master     │
└────────────┬────────────┘
             │ push event
             ▼
┌─────────────────────────┐
│  GitHub Actions          │
│  (ubuntu-latest, 02:00  │
│   UTC daily + manual)   │
│                         │
│  4. pip install deps    │
│  5. init_schema()       │  ← creates fresh DuckDB in-memory (no .duckdb in git)
│  6. run_nightly.py      │  ← steps 1-4 soft-fail; steps 5-9 are critical
│  7. export_json.py      │  ← writes frontend/public/data/*.json
│  8. git commit --push   │  ← [skip ci] so this doesn't re-trigger the action
└────────────┬────────────┘
             │ JSON files committed to repo
             ▼
┌─────────────────────────┐
│  Vercel                 │
│                         │
│  Auto-deploys on every  │  ← detects new commit, rebuilds Next.js site
│  push to master         │
│                         │
│  frontend/public/data/  │  ← static JSON served from CDN edge
│    players.json         │
│    simulations.json     │
│    matchups.json        │
│    brier.json           │
└─────────────────────────┘
```

**Critical implication:** `data/truescout.duckdb` is git-ignored. Every GitHub Actions run starts
with an empty DuckDB. All data must be seeded from Bronze Parquets that are committed to git. If a
Bronze Parquet is not committed, that data source is invisible to CI.

### No FastAPI in production

FastAPI exists for local development (`main.py`, `api/routes/`). The Vercel deployment uses
**no backend server**. `frontend/lib/server-data.ts` reads JSON files directly via `fs.readFileSync`
in Next.js server components. `frontend/lib/api.ts` contains the Axios/fetch client used during
local development (when FastAPI is running).

---

## 3. Data Pipeline & Medallion Layout

### Bronze — raw, as-fetched

`data/bronze/` — committed to git (except `/errors/` subdirectories).

| Path | Source | Contents | Notes |
|---|---|---|---|
| `sofascore/events/` | Sofascore v1 | Match event metadata | One Parquet per round |
| `sofascore/lineups/` | Sofascore v1 | Per-match player lineups + Sofascore ratings | `player_id` dtype: **int64** |
| `sofascore/statistics/` | Sofascore v1 | Per-match player stat rows | |
| `espn/matches/` | ESPN public API | Match results, dates, round names, scores | `round_name` = "Round of 32" etc. |
| `espn/odds/` | ESPN public API | Pre-match 3-way W/D/L odds (American format) | Converted to probabilities |
| `understat/` | Understat (understatapi) | 2-yr xG/xA club stats for EPL/La_Liga/Bundesliga/Serie_A/Ligue_1 | |
| `reep/people/` | Reep register | 444,707-row universal player identity table | `key_sofascore` dtype: **str** |
| `reep/teams/` | Reep register | National team identity | |
| `reep/names/` | Reep register | Name aliases for normalization | |
| `club_elo/` | Club Elo (soccerdata) | 5-row Parquet, league ELO strength coefficients | Pulled once |
| `fbref/` | FBref (dead) | **Empty.** FBref data removed by Opta/Stats Perform Jan 2026 | Keep dir; `fbref_pull.py` archived |

**Bronze Parquet views** in DuckDB are created lazily by `init_db.refresh_parquet_views()`. They
are `CREATE OR REPLACE VIEW` statements, not tables — they query the files at runtime.

### Silver — cleaned, joined feature matrix

`data/silver/player_stats/features.parquet`

Built by `etl/silver/build_features.py`. This is the **only Silver file that matters** for the
model. It joins:
- Sofascore WC lineups (per-match stats aggregated to per-player totals, then per-90)
- Understat club priors (`club_priors_agg.parquet`)
- `identity_players` DuckDB table (to attach `reep_id` and canonical position)

Output: ~3,274 rows × 72 columns. One row per player (either has WC data, club prior, or both).

### Gold — model outputs (static JSON for Vercel)

`frontend/public/data/` — committed to git by GitHub Actions nightly.

| File | Source | Shape |
|---|---|---|
| `players.json` | `player_ratings` + `identity_players` + `archetypes` | Array of ~3,274 player objects with full Bayesian profile |
| `simulations.json` | `simulations` table | `{run_date, n_iterations, rounds[]}` — 32 teams × 6 rounds |
| `matchups.json` | ESPN Bronze Parquets + `simulations` | Keyed by round code (R32/R16/QF/SF/F), model vs market probs |
| `brier.json` | `brier_log` table | Summary stats + per-match calibration log |

Written by `etl/export_json.py`. All numeric fields go through `_safe_float()` to guard against
`None`/`NaN` crashing `json.dumps`.

### DuckDB Tables (in-memory each CI run)

Full DDL in `etl/db/init_db.py`. Key tables for the pipeline:

| Table | Role |
|---|---|
| `identity_players` | Crosswalk: `reep_id` ↔ `key_sofascore`, `key_understat`, name, nationality, position. **Seeded from `data/bronze/reep/people/people.parquet` in step 4 of `run_nightly.py`.** |
| `archetypes` | K-Means cluster assignment per player. Written by `etl/models/archetypes.py`. |
| `player_ratings` | Bayesian posteriors. Written by `etl/models/bayesian_ratings.py`. |
| `simulations` | Monte Carlo results. Fully rewritten each run. |
| `brier_log` | Calibration log. Append-only, UNIQUE on `(event_id, run_date)`. |
| `club_priors` | 2-yr club Understat priors. Written by `etl/load/load_club_priors.py`. |

---

## 4. The Math Engine

### 4.1 Identity Bridge (Reep)

The Reep register (`data/bronze/reep/people/people.parquet`) is the universal player ID crosswalk.
It maps `reep_id` (deterministic hash like `reep_p{hex}`) to external source IDs including
`key_sofascore` (str), `key_understat` (str), `key_espn` (str).

**Loaded into `identity_players` by `etl/load/load_identity.py` (step 4 of `run_nightly.py`).**
Filters to ~83,820 rows where `key_sofascore IS NOT NULL OR key_understat IS NOT NULL`.

Name normalization (for Understat → Reep matching) uses 3-pass Unicode NFD normalization:
strip diacritics, hyphen→space, then a `names.csv` alias fallback. Coverage: 2,774/3,084
WC players mapped.

### 4.2 K-Means Archetype Clustering

`etl/models/archetypes.py`

- **Feature selection:** ElasticNetCV on `wc_rating_avg` target, with prior correlation filter
  (>0.85 drops collinear features). Results in `data/silver/selected_features.json`.
- **Clustering:** RobustScaler + K-Means. Silhouette-optimal k per position bucket:
  `GK=8`, `DEF=3`, `MID=5`, `FWD=3`.
- **Two-tier stratification:**
  - **Macro** (GK/DEF/MID/FWD): used for Bayesian shrinkage math. Each cluster computes
    `cluster_wc_mean` and `cluster_wc_var` as the anchor for the prior.
  - **Micro** (`position_detail` from Reep, e.g. "Defensive Midfielder", "Centre Back"):
    used only for final percentile ranking. A DM's posterior is shrunk toward the MID macro
    mean, but his percentile ranks him against other DMs.

### 4.3 Bayesian Ratings (Normal-Normal Conjugate)

`etl/models/bayesian_ratings.py`

**No MCMC. No PyMC. Pure NumPy/Pandas vectorized update.**

```
Prior:       N(μ_prior, σ²_prior)
  μ_prior    = cluster_wc_mean
               + club_composite_z × cluster_wc_std × PRIOR_PULL   (outfield only)
  σ²_prior   = cluster_wc_var   (variance of wc_rating_avg within cluster)

Likelihood:  N(wc_rating_avg, σ²_wc)
  σ²_wc      = BASE_WC_VAR × 90 / max(wc_minutes, MIN_WC_MINUTES)
               → ∞ for players with no WC data (τ_wc = 0, prior dominates)

Posterior:   N(μ_post, σ²_post)
  τ_post     = τ_prior + τ_wc
  μ_post     = (τ_prior × μ_prior + τ_wc × wc_rating_avg) / τ_post
  σ²_post    = 1 / τ_post

HDI (90%):   μ_post ± 1.645 × σ_post
```

**Key calibration constants** (in `bayesian_ratings.py`):
- `BASE_WC_VAR = 0.30` — per-match Sofascore rating variance (~0.55 std)
- `MIN_WC_MINUTES = 15.0` — floor to avoid near-zero σ²_wc
- `PRIOR_PULL = 0.50` — dampening: 0.0 = pure archetype mean, 1.0 = full Z-score translation
- `MIN_CLUSTER_WC = 5` — minimum WC players per cluster to use cluster stats; smaller → bucket fallback
- `MIN_MICRO_N = 8` — micro-position groups smaller than this collapse to macro fallback

**Confidence gate:**
```python
confidence_score = 0.7 * min(wc_minutes / 270.0, 1.0) + 0.3 * float(has_prior)
```
- `wc_minutes / 270.0`: normalized by 3 full matches (90 min × 3 = 270 min cap)
- `has_prior`: 1.0 if player has Understat club data, 0.0 otherwise
- Range: 0.0 – 1.0. Used to gate LLM voice (threshold: 0.7) and `shrinkage_weight`.

**Fallback guards (critical for CI runs with empty WC data):**
- After the cluster stats merge, `cluster_wc_mean` NaN → filled with `7.0`, `cluster_wc_var` NaN → filled with `0.20`
- `prior_mean` NaN → falls back to `prior_composite` (club-only) or global `6.5`
- `posterior_mean` NaN (e.g. `wc_minutes=0` with no prior) → clamped to `prior_mean`

### 4.4 Monte Carlo Bracket Simulation

`etl/models/monte_carlo_sim.py`

**Constants:**
- `N_SIM = 10_000` iterations (pure NumPy, runs in ~0.04s)
- `TOP_N_PLAYERS = 15` per team for strength calculation
- `LOGISTIC_SCALE = 1.5` — P(A wins | Δstrength=+1.0) ≈ 82%
- `SEED = 42`
- `FALLBACK_STRENGTH = 7.0` — used when a team has no valid posterior ratings

**Team strength:** `mean(posterior_mean)` of the top-15 rated players who appear in the
Sofascore WC lineups for that national team.

**Match winner:**
```python
P(A wins) = 1 / (1 + 10 ** (-(strength_A - strength_B) / LOGISTIC_SCALE))
```

**Bracket construction is data-driven, not hardcoded.** The sim reads actual R32 and R16 fixture
Parquets from ESPN Bronze, then reconstructs the bracket tree from ESPN's "Round of 32 N Winner"
placeholder strings in the R16 fixture descriptions. This means the bracket auto-updates as
matches are played and new fixtures are committed.

**Output:** 192 rows to `simulations` table (32 teams × 6 rounds: R32/R16/QF/SF/F/W).
`title_prob` values sum to 1.0000.

### 4.5 Brier Tracker

`etl/models/brier_tracker.py`

Calibration comparison: TrueScout model vs betting-market odds for completed knockout matches.

**The 2-way knockout conversion (critical):**
ESPN offers 3-way 90-minute odds (H/D/A). Knockout matches cannot end in a draw. Conversion:
```
P_market(home advances) = P(H) + P(D) × et_bias
et_bias = 0.55 if home team is model-stronger, else 0.45
```
The model advance prob uses the same logistic formula as the Monte Carlo sim.

**Metrics:** Brier Score `(p - o)²` and Log Loss `-log(p of outcome)`, clipped at [0.01, 0.99].
Coin-flip baseline: Brier = 0.25, Log Loss = 0.693.

**Idempotency:** `UNIQUE (event_id, run_date)` constraint on `brier_log` prevents double-counting
on re-runs.

---

## 5. Known Landmines & Workarounds

### 5.1 Sofascore 403s on CI

**Symptom:** GitHub Actions log shows `HTTPError: 403 Forbidden` from Sofascore step.  
**Cause:** Cloudflare blocks GitHub Actions datacenter IP ranges regardless of TLS spoofing.  
**Mitigation:** Step 2 (`2_sofascore_pull`) is in `_INGESTION` (non-critical). CI continues using
previously committed Bronze Parquets. The GitHub Action exits 0 as long as steps 5–9 succeed.  
**Action required:** Run `sofascore_pull.py` locally after each matchday and push the new Parquets.

**CRITICAL URL CONSTRAINT:** The Sofascore base URL must remain `https://www.sofascore.com/api/v1`.
Do NOT change it to `https://api.sofascore.com`. The `api.sofascore.com` subdomain is
cross-origin relative to the `Referer: https://www.sofascore.com` header — Cloudflare detects
this mismatch and returns fake 404s. `www.sofascore.com/api/v1` is the only endpoint that works
with `curl_cffi`. This is configured in `config.py:sofascore_base_url` and must not be changed.

### 5.2 DuckDB Write Lock

**Symptom:** `duckdb.IOException: Conflicting lock` or silent deadlock.  
**Cause:** DuckDB's write connection is a singleton per process (`etl/db/connection.py`). Running
`run_nightly.py` and the FastAPI server simultaneously against the same `.duckdb` file will cause
write contention.  
**Mitigation:** Never run the nightly batch while the FastAPI server is live. On the dev machine,
stop FastAPI before running `run_nightly.py` (or any ETL script that writes to DuckDB).  
**Read connections** are safe to use concurrently — `get_read_conn()` returns a cursor on the
write connection, sharing the same underlying connection safely per DuckDB v1.0+ semantics.

### 5.3 The Type-Casting Trap (Sofascore player_id vs Reep key_sofascore)

**Symptom:** `build_sofascore_bridge()` returns 0 rows. WC data cannot join to player_ratings.
All players fall back to prior-only ratings. Simulation becomes a coin flip.  
**Cause:** Sofascore Bronze lineups store `player_id` as **int64** (e.g., `990408`). The
`identity_players` table stores `key_sofascore` as **VARCHAR** (e.g., `"990408"`). A Pandas merge
on mismatched types silently drops all rows — no error, just 0 matches.  
**Fix (in `etl/silver/build_features.py`):**
```python
wc["sofascore_id"]     = wc["sofascore_id"].astype(str)
bridge["sofascore_id"] = bridge["sofascore_id"].astype(str)
wc_reep = wc.merge(bridge, on="sofascore_id", how="left")
```

### 5.4 The 3-Way vs 2-Way Odds Trap

**Symptom:** Brier scores look artificially good/bad. Market probs don't compare fairly to model.  
**Cause:** Betting markets price 90-minute W/D/L odds. The model outputs P(team advances), which
includes extra time and penalties. Using raw P(H wins in 90 min) as the market baseline is wrong.  
**Fix:** The `brier_tracker.py` conversion formula:
```
P_market(home advances) = P(H_90min) + P(Draw_90min) × et_bias
et_bias = 0.55 for the model-stronger side, 0.45 for the weaker side
```

### 5.5 The NaN Cascade

**Symptom:** `posterior_mean` is NaN for all players. Simulation outputs `nan` for all probabilities.
Export crashes with `TypeError: float() argument must be a string or a real number, not 'NoneType'`.  
**Cause:** A chain reaction triggered by empty `identity_players`:
```
identity_players empty
  → build_sofascore_bridge() returns 0 rows
    → WC Parquets get no reep_id → orphaned
      → _compute_anchor_stats() returns empty DataFrame
        → cluster_wc_mean / cluster_wc_var are NaN after merge
          → prior_mean is NaN
            → posterior_mean is NaN
              → SQL NULL in DuckDB → Python None in export
                → float(None) → TypeError
```
**Current mitigations:**
1. `load_identity.py` (step 4) seeds `identity_players` from Bronze before `build_features` runs
2. `bayesian_ratings.py` fills NaN cluster stats with defaults (7.0 / 0.20) after merge
3. `bayesian_ratings.py` clamps NaN `posterior_mean` to `prior_mean`
4. `export_json.py` uses `_safe_float()` on all numeric fields

### 5.6 DuckDB INSERT OR REPLACE Requires a Declared PRIMARY KEY

**Symptom:** `_duckdb.BinderException: Binder Error: There are no UNIQUE/PRIMARY KEY constraints
that refer to this table, specify ON CONFLICT columns manually`  
**Cause:** `CREATE TABLE IF NOT EXISTS` does not alter an existing table. If the local DuckDB was
created before the `PRIMARY KEY` constraint was added to the DDL, the table has no PK and
`INSERT OR REPLACE` fails.  
**Fix pattern used in `load_identity.py`:**
```python
# Stage the data in a temp table, then DELETE existing conflicting rows, then INSERT.
conn.execute("CREATE OR REPLACE TEMP TABLE _id_stage AS SELECT ...")
conn.execute("DELETE FROM identity_players WHERE reep_id IN (SELECT reep_id FROM _id_stage)")
conn.execute("INSERT INTO identity_players (...) SELECT ... FROM _id_stage")
```
This works regardless of whether the live table has a PK constraint.

### 5.7 FBref Is Permanently Dead

**Opta/Stats Perform pulled all advanced metrics (xG, xA, progressive carries, pressures) from
FBref in January 2026** as part of a FIFA betting-data licensing deal. The data does not exist on
the site. `etl/sources/fbref_pull.py` is preserved for reference only. `data/bronze/fbref/` stays
empty. All club prior data comes from **Understat** instead.

---

## 6. Maintenance Workflow

### After a World Cup matchday (standard update)

```
Step 1 — Run scraper locally (residential IP required)
  python -m etl.sources.sofascore_pull --all-rounds
  python -m etl.sources.espn_pull --knockout

Step 2 — Verify new Parquets exist
  ls data/bronze/sofascore/lineups/
  ls data/bronze/espn/matches/

Step 3 — Commit and push the new Bronze files
  git add data/bronze/
  git commit -m "feat: add [round] match data [date]"
  git push origin master

Step 4 — GitHub Actions triggers automatically
  Monitor at: https://github.com/shehzanwar/TrueScout-WC26/actions
  Expected: steps 1-4 soft-fail (Sofascore 403 expected in CI), steps 5-9 must pass.
  Runtime: ~2-4 minutes.

Step 5 — Vercel auto-deploys
  Detects the new commit, rebuilds Next.js, deploys to CDN.
  Dashboard at: https://true-scout.vercel.app/ shows updated odds within ~5 minutes.
```

### Manual trigger (without a new matchday)

From GitHub Actions UI → "Nightly ETL + Static Export" → "Run workflow" → branch: master.

### Local dev server

```bash
# Terminal 1 — FastAPI backend (port 8000, or 8001 if BaseCamp owns 8000)
conda activate wc26
cd S:\Projects\TrueScout
python main.py

# Terminal 2 — Next.js frontend (port 3000)
cd S:\Projects\TrueScout\frontend
npm run dev
```
FastAPI is only needed locally. It is not deployed in production.

### Re-running just the math (no new data)

```bash
# Run individual pipeline steps standalone
python -m etl.load.load_identity          # step 4
python -m etl.silver.build_features       # step 5
python -m etl.models.bayesian_ratings     # step 6
python -m etl.models.monte_carlo_sim      # step 7
python -m etl.models.brier_tracker        # step 8
python etl/export_json.py                 # step 9
```

---

## 7. Key File Directory Map

```
TrueScout/
│
├── run_nightly.py               ← 9-step orchestrator (the main entry point)
├── config.py                    ← Pydantic Settings; all env vars + paths
├── main.py                      ← FastAPI app (local dev only, not deployed)
├── requirements.txt
│
├── .github/workflows/
│   └── nightly.yml              ← GitHub Actions: daily 02:00 UTC + manual trigger
│
├── etl/
│   ├── db/
│   │   ├── init_db.py           ← DDL for all 11 DuckDB tables + Parquet views
│   │   └── connection.py        ← Singleton write conn + cursor-based read conns
│   │
│   ├── sources/                 ← Bronze ingestion (scraping)
│   │   ├── sofascore_pull.py    ← curl_cffi TLS spoof; primary: www.sofascore.com/api/v1
│   │   ├── espn_pull.py         ← httpx; American odds → normalized probs
│   │   ├── understat_pull.py    ← understatapi; xG/xA for 5 top leagues, 2 seasons
│   │   ├── soccerdata_pull.py   ← Club Elo coefficients (pulled once)
│   │   └── fbref_pull.py        ← DEAD. Opta blackout Jan 2026. Do not run.
│   │
│   ├── load/                    ← Bronze → DuckDB loaders
│   │   ├── load_identity.py     ← people.parquet → identity_players (step 4)
│   │   ├── load_group_stage.py  ← ESPN matches → Silver matches (step 3)
│   │   └── load_club_priors.py  ← Understat → club_priors table
│   │
│   ├── silver/
│   │   └── build_features.py    ← WC lineups × club priors → features.parquet (step 5)
│   │
│   ├── models/
│   │   ├── feature_selection.py ← ElasticNetCV → selected_features.json
│   │   ├── archetypes.py        ← K-Means clusters → archetypes table
│   │   ├── bayesian_ratings.py  ← Normal-Normal conjugate → player_ratings (step 6)
│   │   ├── monte_carlo_sim.py   ← 10k-iter logistic bracket → simulations (step 7)
│   │   └── brier_tracker.py     ← model vs market calibration → brier_log (step 8)
│   │
│   └── export_json.py           ← DuckDB tables → frontend/public/data/*.json (step 9)
│
├── api/
│   ├── routes/
│   │   ├── players.py           ← GET /api/v1/players/{reep_id}
│   │   ├── matchups.py          ← GET /api/v1/matchups?round=R32
│   │   ├── simulations.py       ← GET /api/v1/simulations
│   │   ├── brier.py             ← GET /api/v1/brier
│   │   └── narratives.py        ← POST /api/v1/narratives/{reep_id} (OpenRouter LLM)
│   └── deps.py                  ← FastAPI DuckDB dependency injection
│
├── data/
│   ├── bronze/                  ← Raw Parquets — committed to git
│   │   ├── sofascore/events|lineups|statistics/
│   │   ├── espn/matches|odds/
│   │   ├── understat/
│   │   ├── reep/people|teams|names/
│   │   ├── club_elo/
│   │   └── fbref/               ← empty (Opta blackout)
│   ├── silver/player_stats/     ← features.parquet — rebuilt each run (git-ignored)
│   ├── gold/                    ← model output Parquets (git-ignored; JSON is the real export)
│   └── truescout.duckdb         ← git-ignored; rebuilt from scratch on every CI run
│
├── frontend/
│   ├── app/
│   │   ├── page.tsx             ← Home: title leaderboard + Brier calibration card
│   │   ├── matchups/page.tsx    ← Round selector tabs + MatchCard grid
│   │   ├── bracket/page.tsx     ← Interactive CSS knockout tree
│   │   ├── players/page.tsx     ← Debounced player search
│   │   ├── players/[reep_id]/page.tsx  ← Player profile: radar + Bayesian stats + LLM narrative
│   │   └── brier/page.tsx       ← Calibration log + Recharts scatter plot
│   │
│   ├── lib/
│   │   ├── server-data.ts       ← fs.readFileSync — server-only, reads public/data/*.json
│   │   └── api.ts               ← Axios/fetch client — local dev only (points to FastAPI)
│   │
│   └── public/data/             ← Static JSON — committed by GitHub Actions nightly
│       ├── players.json
│       ├── simulations.json
│       ├── matchups.json
│       └── brier.json
│
├── logs/
│   └── nightly.log              ← Rotating log (5 MB × 7 files); git-ignored
│
├── PRD.md                       ← Product requirements (the "what")
├── ARCHITECTURE.md              ← Technical spec (the "how")
├── BOARD.md                     ← Kanban board (the "when" + abandoned decisions)
└── CONTEXT.md                   ← This file (the "save point")
```

---

## 8. Environment & Dependencies

### Conda env

```
conda activate wc26         # Python 3.11
```

### Key packages

| Package | Use |
|---|---|
| `duckdb` | In-process OLAP database + Parquet query engine |
| `curl_cffi` | Browser TLS fingerprint spoofing for Sofascore scraping |
| `httpx` | Async HTTP client for ESPN pull |
| `understatapi` | Understat xG/xA data fetcher |
| `soccerdata` | Club Elo scraper |
| `fastapi` + `uvicorn` | Local development API server |
| `pydantic-settings` | `config.py` settings management |
| `openai` | OpenRouter API client (same interface, different base_url) |
| `scikit-learn` | K-Means, ElasticNetCV, RobustScaler |
| `numpy` + `pandas` | Feature engineering + vectorized Bayesian math |

### Required `.env` keys

```
OPENROUTER_API_KEY=sk-or-...       # required for LLM narratives (get free at openrouter.ai)
DUCKDB_PATH=data/truescout.duckdb  # optional override; defaults to repo root
```

No other secrets required. ESPN and Sofascore are unauthenticated (with TLS spoofing for Sofascore).

---

## 9. Current Model Output (as of 2026-06-29)

Title probability leaders from the most recent CI run:
- France ~7.1%, Spain ~6.4%, Germany ~6.0%, Portugal ~5.9%
- `sum(title_prob)` = 1.0000 (verified)
- 32 teams × 6 rounds = 192 simulation rows

One Brier score logged (South Africa vs Canada): `brier_model = 0.1748 < 0.25 (coin)`.
`brier_skill_vs_coin = 0.30`.

Calibration will improve as more knockout matches are graded.
