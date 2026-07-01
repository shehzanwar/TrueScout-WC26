# TrueScout — Execution Board

> Simple Kanban, not a Gantt chart. Track daily progress here (or mirror to GitHub Projects / Trello /
> Notion). Pairs with [`PRD.md`](PRD.md) and [`ARCHITECTURE.md`](ARCHITECTURE.md).
>
> **Last updated:** 2026-07-01 (Senior audit TS-WC26-001 received; Phase 6 audit remediation sprint started — 3 critical gaps + 8 tournament-safe items)

---

## Columns
`Backlog` (ideas / post-V1) → `To Do` (this week) → `In Progress` (today) → `Blocked` (need to
research/fix) → `Done`

---

## Milestones (Phases)

### Phase 1 — Foundation (UI shell + Database + Ingestion)
Repo scaffold, DuckDB schema, and the data pipeline that feeds everything else.

### Phase 2 — Core Modeling
Bayesian ratings, archetypes, Monte Carlo sim, Brier tracker, FastAPI endpoints, nightly CRON.

### Phase 3 — Polish, LLM & Deploy
Next.js dashboard, OpenRouter RAG narratives, bug-fixing, deployment.

### Phase 4 — Feature Expansion (PR4–PR8)
Joint bracket probability, FIFA-style score, data-quality bug fixes, rest/travel modeling,
narrative pre-generation, Compare Players, home-page insight cards, sitewide tooltips.

### Phase 5 — Reliability, Narratives & Fan Features (Round 3)
AI Analyst stabilization (Poolside Laguna M.1, Vercel timeout fix, fallback chain), remaining
data-integrity gaps (Rating Breakdown jargon, market odds archive, verify_outputs gate), LLM-polished
narrative pre-generation (templated anti-hallucination pattern), story/preview cards, untapped data
utilization (discipline, similarity, age cohorts, more raw stats).

---

## Board

### 🗂️ Backlog (Post-V1 — parked, not lost)
- [ ] Evaluate `wreq` Python HTTP client (BoringSSL/JA4) as `curl_cffi` escalation if Cloudflare fingerprint check tightens again
- [ ] RAPM (opponent-adjusted plus-minus)
- [ ] Dixon-Coles scoreline model
- [ ] Live minute-by-minute firehose
- [ ] KNN "statistical twin" cross-league imputation
- [ ] Monte Carlo **full fatigue model** (minutes-played load, travel distance via haversine on
      `data/static/venues_2026.json` coordinates, squad rotation signal) — needs parameter
      calibration before use. **Partially superseded:** a simple, uncalibrated rest-days penalty
      shipped in Phase 4 (`-0.10 × max(0, 3 - rest_days)` in `monte_carlo_sim.py`) — see Phase 4 Done.
- [ ] WebGL / deck.gl hexbin pitch-event rendering
- [ ] Custom D3 pizza charts + pass networks
- [ ] PostgreSQL for relational data (only if multi-user/concurrent writes appear)
- [ ] Multi-user auth
- [ ] Walk-forward CV / LOTO / PSIS-LOO full validation suite
- [ ] **Time-aware Bayesian ratings v2** — blocked on Silver→model per-match data-flow refactor
      (requires `match_log.parquet` parallel to the per-player aggregate; 2–3 day refactor, high regression risk)
- [ ] **Empirical calibration** (grid-search PRIOR_PULL/OPPONENT_ALPHA/LOGISTIC_SCALE + isotonic regression) —
      blocked on ≥20 graded knockout matches (currently 3; ETA: SF/Final week)
- [ ] **Dixon-Coles scoreline model** — depends on per-match data flow (above)
- [ ] **Player similarity** ("Who plays like X?") — K-Means cosine distance within cluster; `similar_players` field in `players.json`; chip strip on player profile
- [ ] **Discipline posterior + Cards Watch** — yellow/red card rate per 90; homepage leaderboard of highest-risk active players
- [ ] **Age cohort narratives** — propagate Reep `date_of_birth` to export; compute age + cohort percentile (u-21, 22-26, 27-31, 32+); powers breakout/veteran story hooks
- [ ] **Golden Boot / Golden Ball Monte Carlo** — per-player expected goals + rating × minutes accumulated across 10k sims; `awards.json` with top 20 candidates + 90% CI
- [ ] **Day-over-day title prob deltas** — diff today's vs yesterday's `simulations.json` (git history); "+0.3%" arrows on Favorites leaderboard
- [ ] **"What-if" bracket explorer** — click a slot to eliminate a team; title probs re-aggregate from existing 10k sims
- [ ] **Pass completion %, dribbles, duels** — aggregate from Sofascore `statistics` Parquet → per-90 + win-rate; add to raw stats panel
- [ ] **npxG vs xG finishing decomp** — "Finishing: +0.12 G above non-penalty xG/90 (top 10% of forwards)"
- [ ] **Team-level Bayesian posterior** — replace `mean(top-15)` team strength with pooled Normal prior + squad-form posterior; honest uncertainty propagation into Monte Carlo
- [ ] **Attendance × home-crowd boost** — logistic regression on ESPN `attendance` field vs match outcome
- [ ] **Key duels per match** — LLM 1-sentence narration per position overlap pair (FR-RB vs SP-LW etc.)
- [ ] RAPM (opponent-adjusted plus-minus)
- [ ] Live minute-by-minute firehose
- [ ] KNN "statistical twin" cross-league imputation
- [ ] Monte Carlo **full fatigue model** (minutes-played load, travel distance via haversine on
      `data/static/venues_2026.json` coordinates, squad rotation signal) — needs parameter
      calibration before use. **Partially superseded:** a simple, uncalibrated rest-days penalty
      shipped in Phase 4 (`-0.10 × max(0, 3 - rest_days)` in `monte_carlo_sim.py`) — see Phase 4 Done.
- [ ] WebGL / deck.gl hexbin pitch-event rendering
- [ ] Custom D3 pizza charts + pass networks
- [ ] PostgreSQL for relational data (only if multi-user/concurrent writes appear)
- [ ] Multi-user auth
- [ ] Walk-forward CV / LOTO / PSIS-LOO full validation suite
- [ ] Evaluate `wreq` Python HTTP client (BoringSSL/JA4) as `curl_cffi` escalation if Cloudflare fingerprint check tightens again

### 📋 To Do (V1 — this week)
**Phase 1** ✅ complete

**Phase 2**
- [x] Percentile/Z-score calculation **within archetype** — `percentile_rank` computed inside `bayesian_ratings.py`, partitioned by `position_micro` (≥8 players) with fallback to `position_macro`
- [x] Monte Carlo bracket sim (10k+ iters) over remaining teams
- [x] Brier-score tracker: TrueScout vs market odds, append to `brier_log`
- [x] Compute per-player `confidence_score` (league tier + minutes) — `confidence_score = 0.7*(min(wc_minutes/270,1)) + 0.3*(has_prior)` in `bayesian_ratings.py`
- [x] FastAPI endpoints (players, matchups, simulations, brier)
- [x] Wire nightly CRON (Task Scheduler): `run_nightly.py` — 7-step sequential orchestrator, per-step try/except, rotating log to `logs/nightly.log`

**Phase 3**
- [x] Next.js + Tailwind dashboard shell (dark mode) — App Router, Geist font, slate-950, sidebar nav, Framer Motion
- [x] TypeScript API client (`frontend/lib/api.ts`) — all Pydantic interfaces, 8s AbortController timeout
- [x] Home dashboard (`/`) — Top 5 title favorites leaderboard + Brier calibration card, stagger animations
- [x] Matchups page (`/matchups`) — round selector tabs, MatchCard with TrueScout vs market prob bars, flag emojis, edge signal, color-coded confidence, 2→3-col responsive grid
- [x] Player profile page: Recharts radar (5 Bayesian axes) + confidence badge + posterior stats card + prior/WC weight bar
- [x] Player search (`/players`): debounced ILIKE search, flag emojis, color-coded posterior/confidence
- [x] OpenRouter RAG narratives: `POST /api/v1/narratives/{reep_id}` — confidence-gated (≥0.7→Data Analyst/Llama 3.1, <0.7→Traditional Scout); Framer Motion fade-in paragraph reveal; VoiceBadge, 30s timeout, graceful fallback
- [x] Interactive Knockout Tree (`/bracket`) — CSS flex bracket, proportional-flex connector lines (25%/75% arm geometry), Framer Motion whileInView prob bars, confirmed-fixture vs ghosted-projection styling, champion card
- [x] Brier-tracker panel (`/brier`) — 4 summary cards (Brier/skill-score/log-loss/count), sortable MatchLogTable with edge/upset row highlighting, Recharts ComposedChart scatter (model vs market, favorites + upsets, y=x diagonal reference line)
- [x] Deploy: Static JSON export (GitHub Actions nightly) + Next.js API route (Vercel) — see `DEPLOYMENT.md`

**Phase 4**
- [x] Joint bracket-slot probability distribution (vs marginal advance_prob) — `_compute_bracket_slots()`
- [x] FIFA-style 0-99 dual display score (60% absolute + 40% relative percentile)
- [x] National team derivation from Sofascore lineups (separate from Reep bio nationality)
- [x] Percentile label fix ("Top X%" only ≥50th percentile, else "Bottom X%")
- [x] Position override file + ETL hook (`data/static/position_overrides.json`)
- [x] AI narrative jargon removal (posterior/HDI/shrinkage → plain football language)
- [x] Market odds backfill from `brier_log` for completed matches ESPN stripped
- [x] Team alias normalization — shared Python/TypeScript module
- [x] Data-quality audit script (`etl/audits/audit_player_data.py`, 4 checks)
- [x] Rest/travel strength adjustment — `data/static/venues_2026.json` + rest-days penalty in sim
- [x] `/about` "What our model can't yet capture" critique section
- [x] Standalone narrative CLI (`etl/models/generate_narratives.py`) — built; removed from nightly
      pipeline (OpenRouter free-tier rate limits make automated batch impractical). Live on-demand
      generation via "Generate Scouting Report" button remains the active path.
- [x] Compare Players (`/compare`) — side-by-side rating/attribute comparison
- [x] Home page insight cards — Next Match, Value Pick, Top Performers
- [x] Templated (non-LLM) match preview line on `MatchCard`
- [x] Bracket share button (copy link)
- [x] Sitewide tooltips wired into player profile Rating Breakdown

**Phase 5**

PR5c — finish data-integrity gaps (blocking — ship first):
- [x] Strip jargon from Rating Breakdown card — labels already clean in `page.tsx` (done Phase 4)
- [x] Full `market_odds_archive`: new DuckDB table in `init_db.py`; `_populate_market_odds_archive()` in `export_json.py` populates from Bronze odds Parquets (first-seen-wins); archive + brier_log fallback chain in `export_matchups()`
- [x] Frontend `teamAliases.ts` — already existed and mirrors ETL `team_aliases.py` exactly
- [x] Standalone `etl/verify_outputs.py` as step 9.5 in nightly pipeline (hard-fail on title_prob sum, player count, confidence range, matchup structure)
- [x] Travel km chip on MatchCard — haversine `_build_travel_km()` in `export_json.py`; `travel_km` field in `MatchupTeam` type; chip displayed below rest_days chip (amber ≥ 2000 km)

PR5d — AI Analyst stabilization (urgent):
- [x] Vercel route: `export const runtime = "nodejs"`, `maxDuration = 60`, `dynamic = "force-dynamic"`
- [x] Reasoning-tag strip (`<think>…</think>`, `<reasoning>…</reasoning>`) via `stripReasoningTags()`
- [x] `max_tokens` raised to 800; abort timeout raised to 55s
- [x] Fallback model chain: env primary → `google/gemma-3-27b-it:free` → `nvidia/llama-3.1-nemotron-70b-instruct:free` → `meta-llama/llama-3.3-70b-instruct:free`
- [x] Module-level `players.json` cache via `getPlayers()` (shared across warm starts)
- [x] `config.py` default model → `poolside/laguna-m.1:free`

PR7 — Narrative pre-gen (re-implement after PR5d, with hardened approach):
- [ ] `etl/models/generate_narratives.py` wired into nightly step 9.6 with Laguna M.1 primary
- [ ] Templated anti-hallucination pattern: Python emits structured fact bullets; LLM only rephrases; system prompt bans inventing numbers
- [ ] Frontend short-circuit: pre-gen narrative → instant display; sparse-data players keep "Generate" button

PR8 extras — story/insight features (after PR7):
- [ ] Story of the day: ETL diffs overnight sim swings + largest model–market gap; LLM polishes 1-sentence headline; writes `insights.json`
- [ ] LLM-polished pre-match preview cards (~32 calls/matchday): Python templates top creator + scoreline + rest delta; LLM polishes to 80-word preview

PR9 — Untapped data utilization:
- [ ] Discipline posterior + Cards Watch leaderboard
- [ ] Age cohort field + cohort percentile from Reep DOB
- [ ] Player similarity chip ("Who plays like X?") from K-Means cosine distance
- [ ] Pass completion %, dribbles, aerial duels from Sofascore statistics
- [ ] npxG vs xG finishing decomposition
- [ ] Golden Boot / Golden Ball Monte Carlo projections

**Phase 6 — Audit Remediation (TS-WC26-001, 2026-07-01)**

Critical gaps (§9.2 — genuinely new work not in the PR plan):
- [x] **Gap 1** — Mobile sidebar collapse: `hidden lg:flex` on `<aside>`, new `SidebarClient.tsx` (sticky top bar + hamburger + slide-in drawer + auto-close on nav)
- [x] **Gap 2** — Add Compare to sidebar nav: one entry in `Sidebar.tsx` NAV array + `SidebarClient.tsx` NAV array (~1h)
- [x] **Gap 3** — Brier 90-min draw-skip fix: resolve ET/pens winner from Sofascore `home_score_et`/`away_score_et` instead of `continue`; de-dup stale `_NAME_ALIASES` in `brier_tracker.py:65-75` + `matchups.py:59-67` → import canonical `TEAM_ALIASES` (~4h)

Tournament-safe items (§10.2 — no math core changes):
- [ ] Keyboard-accessible sort buttons + `aria-sort` on `MatchLogTable.tsx` (~4h)
- [ ] Parameterised SQL in `load_identity._apply_position_overrides` (`load_identity.py:159-165`) (~1h)
- [ ] Nightly failure alerting — Slack/Discord webhook on critical step failure in `run_nightly.py` (~2h)
- [ ] Remove dead deps (`pymc`, `apscheduler`, `rich`) + pin critical-path deps with `~=` in `requirements.txt` (~1h)
- [ ] Move `fbref_pull.py` → `etl/sources/_archive/`; delete empty `etl/matching/` stub (~30m)
- [ ] Hedge Value Pick card + add storyline tags to Title Favorites in `HomeCards.tsx` (~1h)
- [ ] Add venue names to `MatchCard.tsx` from `venues_2026.json` (~1h)
- [ ] PWA wrapper (`manifest.json` + service worker for offline-tolerant nav) (~4h)

Deferred (§10.3 — touch math core, ship after tournament):
- [ ] Remove WC-floor override (`monte_carlo_sim.py:321-329`) — needs calibration run vs PR 5.4 output
- [ ] Propagate per-player posterior uncertainty into Monte Carlo (`monte_carlo_sim.py:521-535`)
- [ ] Refactor monolithic `export_json.py` (1,388 lines) into `etl/export/*`
- [ ] Replace recharts radar with hand-rolled SVG polygon (`PlayerRadar.tsx`)

### 🔨 In Progress (today)
- _(empty — pull from To Do)_

### 🚧 Blocked
_(none)_

### ❌ Abandoned
- **FBref club priors** — **Permanently dead.** In January 2026, Opta/Stats Perform pulled all advanced metrics (xG, xA, progressive carries, pressures) from FBref as part of a FIFA betting-data licensing deal. The data no longer exists on the site regardless of Cloudflare bypass. `fbref_pull.py` kept for reference only.
- **FotMob via `sportly` SDK** — `sportly` v1.1.0 IS real (`pip install git+https://github.com/pseudo-r/sportly.git`); installed in wc26 env. But FotMob's API gateway returns 404 for all `/api/*` routes unless the request includes an `x-mas` HMAC token generated inside the mobile app's JS bundle. Every endpoint tested (leagues, matchDetails, matches, playerData) returns 404 HTML. Deferred to V2 scope. `sportly.fotmob` client code is preserved in env for future use.

### ✅ Done
- [x] Verify report flaws & lock V1 scope (daily batch, drop RAPM/Dixon-Coles, DuckDB-only, OpenRouter)
- [x] Write `PRD.md`, `ARCHITECTURE.md`, `BOARD.md`
- [x] Scaffold repo: `requirements.txt`, FastAPI app skeleton (`main.py`), config, `.env.example`, `.gitignore`
- [x] Define DuckDB schema — 11 tables in `etl/db/init_db.py` (verified: `py -m etl.db.init_db`)
- [x] Set up Parquet cache directory structure (bronze/silver/gold Medallion layout)
- [x] Write `etl/sources/soccerdata_pull.py` — Club Elo league-strength coefficients → Bronze Parquet + DuckDB `leagues` (FBref path removed; data pulled Jan 2026)
- [x] Write `etl/sources/understat_pull.py` — `understatapi` xG/xA club priors for EPL/La_Liga/Bundesliga/Serie_A/Ligue_1, 2 seasons (2024-25 + 2025-26), 90s-weighted aggregate → `data/bronze/understat/`; output `player_id = reep_id` after identity join
- [x] Write `etl/sources/reep_pull.py` — canonical identity bridge from `github.com/withqwerty/reep`; streams 66MB `people.csv` + 4MB `teams.csv` via DuckDB httpfs → `data/bronze/reep/`; populates `identity_players` + `identity_teams` DuckDB tables with `key_understat`, `key_sofascore`, `key_espn`, `key_fotmob` etc. → enables deterministic cross-source joins via `reep_id`
- [x] Update `etl/db/init_db.py` — added `identity_players` and `identity_teams` DDL; `reep_id` column on `teams`; reep in `_BRONZE_SOURCES`; `sportly` and `reep-cli` documented in `requirements.txt`
- [x] Write `etl/sources/sofascore_pull.py` — curl_cffi TLS-spoof, primary/fallback domain, integer-ID resolution chain → Bronze Parquet (events/lineups/statistics), 3 DuckDB views
- [x] Write `etl/sources/espn_pull.py` — httpx + Pydantic v2 schema validation, American-odds → normalised Brier probabilities, `--group-stage` sweep → Bronze Parquet (matches/odds), 2 DuckDB views
- [x] Load completed group-stage results as the initial likelihood — `etl/load/load_group_stage.py` (48 teams, 72 matches, 12 groups verified)
- [x] Fix Sofascore host — `www.sofascore.com/api/v1` (was `api.sofascore.com`; cross-origin mismatch caused Cloudflare fake-404)
- [x] Sofascore group-stage sweep — `--all-rounds` pulled rounds 1/2/3 (72 events, 3693 lineup rows, 9051 stat rows); knockout rounds 404 gracefully (not yet played)
- [x] Fix Understat → reep_id mapping (29% → 90%): 3-pass Unicode normalization (NFD + strip diacritics + hyphen→space), names.csv alias support, uniqueness gate — 2774/3084 players mapped, all major WC stars confirmed
- [x] Silver feature matrix (`etl/silver/build_features.py`) — joins WC Sofascore lineups + Understat club priors via reep_id; per-90 WC stats; `wc_low_data` flag; 3274 players, 72 cols (`data/silver/player_stats/features.parquet`)
- [x] Elastic Net feature selection (`etl/models/feature_selection.py`) — correlation filter (>0.85) + ElasticNetCV with `wc_rating_avg` target; selected features per bucket written to `data/silver/selected_features.json`
- [x] K-Means archetype clustering (`etl/models/archetypes.py`) — RobustScaler, silhouette-optimal k per bucket (GK=8, DEF=3, MID=5, FWD=3); 3274 players upserted to `archetypes` DuckDB table; tactically validated (Haaland/Mbappé→FWD-2, De Bruyne→MID-4, Bellingham→MID-1, Messi→FWD-0)
- [x] Hierarchical Bayesian ratings (`etl/models/bayesian_ratings.py`) — analytical Normal-Normal conjugate shrinkage (no MCMC); two-tier stratification (Macro: GK/DEF/MID/FWD for math; Micro: reep position_detail for percentiles); prior=club composite×ELO/cluster variance; likelihood=WC Sofascore rating/f(minutes); 3274 posteriors + 90% HDI + confidence_score + micro-percentile upserted to `player_ratings` table. Validated: Rodri pct=1.00 among DMs, Mbappé post=8.07 (w=0.77), Messi WC-dominated from MLS prior
- [x] Monte Carlo bracket sim (`etl/models/monte_carlo_sim.py`) — logistic strength-delta model; team_strength = avg posterior_mean of top-15 rated players per team; **data-driven bracket**: reads actual 16 R32 + 8 R16 fixtures from Bronze ESPN Parquets (via `espn_pull --knockout`), no hardcoded group-position logic; pure NumPy vectorisation, 10k iters in 0.04s; 192 rows upserted to `simulations` (32 teams × 6 rounds). Title favourites: France 7.1%, Spain 6.4%, Germany 6.0%, Portugal 5.9%. Title prob sum = 1.0000 ✓; all 32 teams with 15 players ✓
- [x] Brier-score tracker (`etl/models/brier_tracker.py`) — 2-way knockout calibration; ESPN 3-way W/D/L odds collapsed via `P(home adv) = P(H) + P(D) × et_bias` (0.55/0.45 for stronger/weaker side); Brier Score + Log Loss + coin-flip baseline; idempotent upsert to `brier_log`. Validated: SA vs Canada (Brier 0.1748 < coin 0.25 ✓, brier_skill_vs_coin=0.30)
- [x] FastAPI endpoints (`api/routes/`): `GET /api/v1/players/{reep_id}`, `GET /api/v1/matchups?round=R32`, `GET /api/v1/simulations`, `GET /api/v1/brier` — Pydantic response models, CORS for localhost:3000, read-only DuckDB cursors on write connection. All 4 endpoints return 200 OK. Bug fixes: DuckDB `read_only=True` blocked by existing write connection → cursor-based reads; `round` param shadowing built-in `round()` in matchups.py → renamed to `round_param`; `brier_log CREATE OR REPLACE` wiping data on each restart → `CREATE TABLE IF NOT EXISTS`
- [x] Nightly orchestrator (`run_nightly.py`) — 7-step sequential pipeline (ESPN → Sofascore → load_group_stage → build_features → bayesian_ratings → monte_carlo_sim → brier_tracker); direct `main()` imports (no subprocess); per-step `try/except` with soft-fail on all ETL steps; rotating log to `logs/nightly.log` (5 MB × 7 files); non-zero exit on any failure for Task Scheduler detection. **Phase 2 COMPLETE.**
