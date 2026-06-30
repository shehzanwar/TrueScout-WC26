# TrueScout — Lean PRD

> **Source of truth.** If it's not in this PRD, we aren't building it yet. Lives in the repo
> alongside the code so scope and reality never drift apart.
>
> **Status:** V1 — "Knockout Stage Intelligence Dashboard" · **Last updated:** 2026-06-30

---

## Problem Statement
The 48 nations at the 2026 World Cup play in wildly different leagues, so their raw stats can't be
compared apples-to-apples — making it impossible to judge a player's *true* quality or predict
knockout outcomes without league and context bias.

---

## Target User
- **Primary:** the solo developer — a football-analytics enthusiast who wants a rigorous, unbiased
  lens on the knockout rounds (and a serious portfolio piece).
- **Secondary:** analytics-minded fans who want context-adjusted scouting profiles and
  data-driven bracket odds, explained in plain language.

---

## Success Metrics
The MVP is successful if:
1. **It runs itself.** The nightly batch completes end-to-end unattended after each knockout matchday
   — fetch completed matches → update priors → recompute ratings → re-simulate → log Brier — within a
   bounded time window (target: under ~15 min on the dev's machine).
2. **It profiles any knockout player.** For any player on a Round-of-32 squad, the dashboard shows a
   league-adjusted percentile profile (within position/archetype) plus a role-aware LLM narrative.
3. **It predicts and grades itself.** It produces calibrated win probabilities for every remaining
   matchup, and logs a Brier score against betting-market odds after each round.
4. **It's fast to read.** "Open the dashboard and within ~30 seconds see updated title odds for every
   remaining team plus a tactical breakdown of the next matchup."

---

## In-Scope (Core Features — V1)
1. **Daily batch ingestion.** End-of-day CRON pulls completed knockout matches from Sofascore (via
   `curl_cffi` TLS spoofing) with ESPN as fallback, caching everything to DuckDB/Parquet. The
   completed group stage is loaded once as the initial Bayesian *likelihood*.
2. **Hierarchical Bayesian player ratings.** 2-year club-season data forms the *prior*, scaled by a
   league-strength coefficient; World Cup minutes update it as the *likelihood*. Partial pooling
   shrinks low-minute players toward their archetype average. Output: percentiles **within position/
   archetype**.
3. **Monte Carlo knockout simulation.** 10,000+ iterations over the *remaining* bracket, re-run each
   matchday, producing per-team advancement and title probabilities, surfaced as an interactive
   "Knockout Tree."
4. **Brier-score tracker.** After each round, compares TrueScout's match probabilities to
   betting-market odds and logs the Brier score for both — a measured calibration check, not a
   "we beat the market" claim.
5. **RAG "Tactical Storytelling."** A confidence-gated, role-aware narrative layer (OpenRouter free
   model). High-confidence players get a metrics-driven "Data Analyst" voice; sparse-data players get
   a "Traditional Scout" voice that is explicitly forbidden from inventing stats. Reports are
   **pre-generated nightly** for high-confidence players and served as static JSON; live generation
   via the "Generate Report" button is the fallback for everyone else.

---

## V1.x — Post-Launch Feature Expansion

Shipped after the initial V1 launch, still within the original problem statement and target user —
not a scope change, just deeper coverage of "judge a player's true quality" and "predict knockout
outcomes":
- **Compare Players** (`/compare`) — side-by-side rating and attribute comparison between any two players.
- **Home-page insight cards** — Next Match, Value Pick (biggest model-vs-bookies gap), Top Performers.
- **Templated match previews** — pure-logic, non-LLM one-line blurbs on each matchup card.
- **Rest-days strength adjustment** — a simple, explicitly uncalibrated penalty for short turnarounds
  between matches (`-0.10 × max(0, 3 - rest_days)`). This is **not** the full fatigue model in
  `BOARD.md` Backlog (which would add travel distance and minutes-load); see Out-of-Scope below.
- **Data-quality fixes** — national-team derivation from lineups (vs. bio nationality), position
  override file, team-name alias normalization, market-odds backfill, an audit script to catch
  future regressions of these classes of bug.

---

## Out-of-Scope (The "Not-Doing" List)
Explicitly **not** building in V1 — parked in `BOARD.md` Backlog so they're deferred, not lost:
- **No live minute-by-minute firehose** — daily batch only.
- **No RAPM and no Dixon-Coles model** — dropped for V1.
- **No KNN "statistical twin" imputation** — we will not fabricate missing advanced metrics; the
  confidence score routes sparse players to the no-stats LLM path instead.
- **No WebGL / deck.gl hexbin pitch-event rendering** — lightweight radar/charts only.
- **No full Monte Carlo fatigue model** — minutes-load and travel-distance fatigue parameters are
  deferred until calibrated. (A simple, uncalibrated rest-days penalty shipped in V1.x — see above —
  but it is not a substitute for the calibrated model.)
- **No multi-user auth** — single-user local/self-hosted app, no login.
- **No PostgreSQL** — DuckDB + Parquet only in V1.
- **No native mobile app** — responsive web only.

---

## User Flow (A → Z)
1. **CRON fires** after the day's knockout match(es) finish.
2. **Fetch** completed match data (Sofascore → ESPN fallback), cache to Parquet/DuckDB.
3. **Update priors** with the new match results as additional likelihood.
4. **Recompute** player ratings and archetype clusters.
5. **Re-run** the Monte Carlo simulation over the remaining bracket.
6. **Log** TrueScout vs. market probabilities and the resulting Brier scores.
7. **Cache** all computed results for fast reads.
8. **User opens the dashboard** → sees updated title odds + the Knockout Tree.
9. **User clicks a matchup** → reads the LLM tactical breakdown + win probabilities.
10. **User clicks a player** → sees their league-adjusted percentile radar + role-aware narrative and
    a data-confidence indicator.
