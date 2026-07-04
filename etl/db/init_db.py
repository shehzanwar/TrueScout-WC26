"""
DuckDB schema bootstrap — idempotent.

Run once (and freely re-run):
    python etl/db/init_db.py

Also called automatically from the FastAPI lifespan on every startup,
so schema changes are picked up without a separate migration step in V1.

Table hierarchy (→ denotes a logical FK; DuckDB declares but does not enforce FKs):

    leagues
      └─ teams
           └─ players
                └─ squads
                └─ club_priors    (Bayesian prior — 2-yr club stats)
                └─ archetypes     (K-Means cluster, Phase 2)
                └─ player_ratings (posterior output, Phase 2)
                └─ player_match_stats → matches

    matches
      └─ brier_log               (append-only calibration tracker, Phase 2)

    simulations                  (rewritten each nightly run, Phase 2)
"""
import logging
from pathlib import Path

import duckdb

from config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Table DDL  — ordered by dependency (parents before children)
# ---------------------------------------------------------------------------

_TABLES: list[str] = [
    # ── Identity / cross-source resolution (reep register) ──────────────────
    """
    CREATE TABLE IF NOT EXISTS identity_players (
        reep_id           VARCHAR PRIMARY KEY,  -- 'reep_p{hash}'
        name              VARCHAR,
        full_name         VARCHAR,
        date_of_birth     DATE,
        nationality       VARCHAR,
        position          VARCHAR,
        position_detail   VARCHAR,
        height_cm         DOUBLE,
        key_fbref         VARCHAR,
        key_sofascore     VARCHAR,
        key_espn          VARCHAR,
        key_understat     VARCHAR,
        key_fotmob        VARCHAR,
        key_transfermarkt VARCHAR,
        key_wyscout       VARCHAR,
        key_whoscored     VARCHAR,
        key_opta          VARCHAR,
        key_wikidata      VARCHAR,
        updated_at        TIMESTAMP DEFAULT now()
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS identity_names (
        reep_id     VARCHAR NOT NULL,  -- FK -> identity_players.reep_id
        name        VARCHAR,
        alias       VARCHAR NOT NULL,
        key_wikidata VARCHAR
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS identity_teams (
        reep_id           VARCHAR PRIMARY KEY,  -- 'reep_t{hash}'
        name              VARCHAR,
        country           VARCHAR,
        founded           VARCHAR,
        stadium           VARCHAR,
        key_espn          VARCHAR,
        key_sofascore     VARCHAR,
        key_fbref         VARCHAR,
        key_fotmob        VARCHAR,
        key_understat     VARCHAR,
        key_transfermarkt VARCHAR,
        key_clubelo       VARCHAR,
        key_opta          VARCHAR,
        key_wikidata      VARCHAR,
        updated_at        TIMESTAMP DEFAULT now()
    )
    """,

    # ── Reference / dimension tables ────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS leagues (
        id                 VARCHAR PRIMARY KEY,   -- e.g. 'eng-premier-league'
        name               VARCHAR NOT NULL,
        country            VARCHAR,
        elo_strength_coef  DOUBLE  DEFAULT 1.0,  -- scaled; top league = 1.0
        elo_rating         DOUBLE,               -- raw Club Elo rating
        updated_at         TIMESTAMP DEFAULT now()
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS teams (
        id             VARCHAR PRIMARY KEY,   -- 'espn-{id}' for national sides; club IDs TBD
        name           VARCHAR NOT NULL,
        short_name     VARCHAR,
        league_id      VARCHAR,              -- → leagues.id
        is_national    BOOLEAN DEFAULT FALSE,
        reep_id        VARCHAR,             -- → identity_teams.reep_id (nullable; Phase 2 join)
        sofascore_id   BIGINT,
        espn_id        VARCHAR,
        fbref_id       VARCHAR,
        updated_at     TIMESTAMP DEFAULT now()
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS players (
        id             VARCHAR PRIMARY KEY,   -- reep_id ('reep_p{hash}') once identity bridge runs
        name           VARCHAR NOT NULL,
        team_id        VARCHAR,              -- → teams.id  (current club)
        position       VARCHAR,             -- GK | CB | FB | CM | AM | W | ST
        nationality    VARCHAR,
        date_of_birth  DATE,
        age_at_wc2026  INTEGER,
        sofascore_id   BIGINT,              -- kept for direct Sofascore Bronze joins
        espn_id        VARCHAR,
        fbref_id       VARCHAR,
        understat_id   VARCHAR,
        updated_at     TIMESTAMP DEFAULT now()
    )
    """,

    # ── Tournament roster ────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS squads (
        player_id        VARCHAR NOT NULL,   -- → players.id
        national_team_id VARCHAR NOT NULL,   -- → teams.id  (national side)
        tournament       VARCHAR NOT NULL DEFAULT 'FIFA World Cup 2026',
        jersey_number    INTEGER,
        squad_role       VARCHAR,            -- starter | bench | reserve
        PRIMARY KEY (player_id, tournament)
    )
    """,

    # ── Bayesian prior (2-yr club-season aggregate from FBref) ───────────────
    """
    CREATE TABLE IF NOT EXISTS club_priors (
        player_id                        VARCHAR NOT NULL,  -- → players.id
        season_window                    VARCHAR NOT NULL,  -- '2023-24+2024-25'
        club_team_id                     VARCHAR,           -- → teams.id
        league_id                        VARCHAR,           -- → leagues.id

        -- Volume
        matches_played                   DOUBLE,
        minutes_played                   DOUBLE,

        -- Attacking (per 90 min)
        goals_per_90                     DOUBLE,
        assists_per_90                   DOUBLE,
        xg_per_90                        DOUBLE,
        xa_per_90                        DOUBLE,
        npxg_per_90                      DOUBLE,  -- non-penalty xG / 90
        shots_per_90                     DOUBLE,
        shots_on_target_pct              DOUBLE,

        -- Creation (per 90 min)
        sca_per_90                       DOUBLE,  -- shot-creating actions
        gca_per_90                       DOUBLE,  -- goal-creating actions
        key_passes_per_90                DOUBLE,

        -- Passing / progression (per 90 min)
        pass_completion_pct              DOUBLE,
        progressive_passes_per_90        DOUBLE,
        progressive_carries_per_90       DOUBLE,
        carries_into_final_third_per_90  DOUBLE,

        -- Defending (per 90 min)
        pressures_per_90                 DOUBLE,
        pressure_success_pct             DOUBLE,
        tackles_per_90                   DOUBLE,
        tackle_success_pct               DOUBLE,
        interceptions_per_90             DOUBLE,
        clearances_per_90                DOUBLE,
        aerials_won_pct                  DOUBLE,

        -- GK-specific (NULL for outfield players)
        save_pct                         DOUBLE,
        psxg_minus_ga_per_90             DOUBLE,  -- Post-Shot xG minus GA / 90
        clean_sheet_pct                  DOUBLE,

        -- Metadata
        data_source  VARCHAR   DEFAULT 'fbref',
        fetched_at   TIMESTAMP DEFAULT now(),

        PRIMARY KEY (player_id, season_window)
    )
    """,

    # ── Phase 2 model outputs ────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS archetypes (
        reep_id          VARCHAR PRIMARY KEY,  -- → identity_players.reep_id
        position_bucket  VARCHAR,              -- GK | DEF | MID | FWD
        cluster_id       INTEGER,
        cluster_label    VARCHAR,              -- optional human label (Phase 3)
        silhouette_score DOUBLE,
        updated_at       TIMESTAMP DEFAULT now()
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS player_ratings (
        reep_id          VARCHAR PRIMARY KEY,
        position_macro   VARCHAR,   -- GK | DEF | MID | FWD
        position_micro   VARCHAR,   -- e.g. "Centre Back", "Defensive Midfielder"
        cluster_id       INTEGER,   -- K-Means cluster from archetypes table
        prior_mean       DOUBLE,    -- predicted wc_rating from club composite + ELO
        posterior_mean   DOUBLE,    -- Normal-Normal posterior mean
        posterior_std    DOUBLE,    -- posterior standard deviation
        hdi_low          DOUBLE,    -- 90% credible interval lower  (mu - 1.645*sigma)
        hdi_high         DOUBLE,    -- 90% credible interval upper  (mu + 1.645*sigma)
        shrinkage_weight DOUBLE,    -- w: 0=fully-prior  1=fully-WC
        wc_minutes       DOUBLE,
        confidence_score DOUBLE,    -- 0.0-1.0 (0.7*wc_conf + 0.3*has_prior)
        percentile_rank  DOUBLE,    -- 0.0-1.0 rank within position_micro group
        updated_at       TIMESTAMP DEFAULT now()
    )
    """,

    # ── Match data (WC likelihood source) ───────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS matches (
        id                 VARCHAR PRIMARY KEY,  -- '{tournament}-{round}-{home}-{away}-{date}'
        tournament         VARCHAR NOT NULL DEFAULT 'FIFA World Cup 2026',
        round              VARCHAR NOT NULL,
            -- group_stage | round_of_32 | round_of_16 | quarter_final
            -- semi_final  | third_place | final
        home_team_id       VARCHAR,  -- → teams.id
        away_team_id       VARCHAR,  -- → teams.id
        match_date         TIMESTAMP,
        venue              VARCHAR,

        -- Score
        home_score         INTEGER,
        away_score         INTEGER,
        home_score_aet     INTEGER,  -- after extra time (NULL if 90-min finish)
        away_score_aet     INTEGER,
        home_penalties     INTEGER,
        away_penalties     INTEGER,
        went_to_extra_time BOOLEAN DEFAULT FALSE,
        went_to_penalties  BOOLEAN DEFAULT FALSE,
        winner_team_id     VARCHAR, -- → teams.id  (who actually advances)
        result_after_90    VARCHAR, -- 'home' | 'draw' | 'away'
        result_final       VARCHAR, -- 'home' | 'away'  (no draw in knockouts)

        -- Market odds snapshot at fetch time (used as Brier baseline)
        market_home_prob   DOUBLE,
        market_draw_prob   DOUBLE,
        market_away_prob   DOUBLE,

        -- Source IDs
        sofascore_id       BIGINT,
        espn_id            VARCHAR,
        fetched_at         TIMESTAMP DEFAULT now(),
        is_completed       BOOLEAN DEFAULT FALSE
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS player_match_stats (
        player_id        VARCHAR NOT NULL,  -- → players.id
        match_id         VARCHAR NOT NULL,  -- → matches.id
        team_id          VARCHAR,           -- → teams.id
        minutes_played   INTEGER DEFAULT 0,
        started          BOOLEAN DEFAULT FALSE,

        -- Scoring
        goals            INTEGER DEFAULT 0,
        assists          INTEGER DEFAULT 0,
        xg               DOUBLE,
        xa               DOUBLE,

        -- Shooting
        shots            INTEGER DEFAULT 0,
        shots_on_target  INTEGER DEFAULT 0,

        -- Passing
        passes_completed INTEGER DEFAULT 0,
        passes_attempted INTEGER DEFAULT 0,
        key_passes       INTEGER DEFAULT 0,

        -- Defending
        tackles          INTEGER DEFAULT 0,
        interceptions    INTEGER DEFAULT 0,
        clearances       INTEGER DEFAULT 0,

        -- Sofascore per-match rating (0–10)
        sofascore_rating DOUBLE,

        PRIMARY KEY (player_id, match_id)
    )
    """,

    # ── Calibration tracker (append-only, Phase 2) ──────────────────────────
    # 2-way knockout schema: P(home advances) vs actual outcome.
    # model_prob / market_prob are both "P(home team advances)".
    # market_prob is derived from ESPN 3-way 90-min odds collapsed to 2-way
    # via: P(home adv) = P(H) + P(D) * et_bias  (et_bias = 0.55 for stronger side)
    """
    CREATE TABLE IF NOT EXISTS brier_log (
        id               VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
        run_date         DATE    NOT NULL,
        round            VARCHAR NOT NULL,
        event_id         VARCHAR,             -- ESPN event_id for idempotency
        home_team        VARCHAR NOT NULL,
        away_team        VARCHAR NOT NULL,
        advanced_team    VARCHAR NOT NULL,    -- who actually advanced

        -- 2-way advance probabilities (P(home advances))
        model_prob       DOUBLE,             -- logistic strength-delta model
        market_prob      DOUBLE,             -- vig-removed ESPN odds (NULL if unavailable)

        -- Per-match scoring (binary, lower is better)
        brier_model      DOUBLE,             -- (model_prob - outcome)^2
        brier_market     DOUBLE,             -- (market_prob - outcome)^2
        log_loss_model   DOUBLE,             -- -log(model prob of actual outcome)
        log_loss_market  DOUBLE,             -- -log(market prob of actual outcome)

        logged_at        TIMESTAMP DEFAULT now(),
        UNIQUE (event_id, run_date)
    )
    """,

    # ── Market odds archive (append-only; preserves pre-match odds) ─────────
    # ESPN strips odds after kickoff. This table snapshots the *first* odds we
    # see for each event so they're available even after the match completes.
    # Populated in export_json.py from Bronze Parquets via INSERT OR IGNORE.
    """
    CREATE TABLE IF NOT EXISTS market_odds_archive (
        event_id      VARCHAR NOT NULL,
        first_seen    DATE    NOT NULL,
        home_win_prob DOUBLE,
        draw_prob     DOUBLE,
        away_win_prob DOUBLE,
        fetched_at    TIMESTAMP DEFAULT now(),
        PRIMARY KEY (event_id)
    )
    """,

    # ── Simulation output (rewritten each nightly run, Phase 2) ─────────────
    """
    CREATE TABLE IF NOT EXISTS simulations (
        run_date     DATE    NOT NULL,
        round        VARCHAR NOT NULL,  -- the round from which this sim was run
        team_id      VARCHAR NOT NULL,  -- → teams.id
        advance_prob DOUBLE,            -- P(advance past the current round)
        title_prob   DOUBLE,            -- P(win the tournament)
        n_iterations INTEGER DEFAULT 10000,
        PRIMARY KEY (run_date, round, team_id)
    )
    """,

    # ── Per-match Bradley-Terry probabilities (pre-simulation, pre-lock-in) ──
    # Stores the raw head-to-head logistic probability for each R32 match so
    # the matchups page can display what the model predicted for each game
    # rather than the post-lock-in simulation advance_prob (which jumps to 1.0
    # for completed match winners once the bracket lock-in is applied).
    """
    CREATE TABLE IF NOT EXISTS match_probs (
        run_date   DATE    NOT NULL,
        team_left  VARCHAR NOT NULL,   -- bracket_order[2j]
        team_right VARCHAR NOT NULL,   -- bracket_order[2j+1]
        prob_left  DOUBLE  NOT NULL,   -- P(team_left wins)
        prob_right DOUBLE  NOT NULL,   -- P(team_right wins)
        PRIMARY KEY (run_date, team_left, team_right)
    )
    """,
]


# ---------------------------------------------------------------------------
# Parquet Bronze VIEWs
#
# DuckDB v1.0 validates the glob pattern at CREATE VIEW time, so views over
# empty directories raise an IOException.  We therefore create them lazily:
# call refresh_parquet_views() after each ingestion batch, and again on startup
# (where it silently skips any source that has no files yet).
# ---------------------------------------------------------------------------

_BRONZE_SOURCES: dict[str, str] = {
    # Sofascore has 3 file types per date — each needs its own view (different schemas)
    "sofascore/events":     "v_bronze_sofascore_events",
    "sofascore/lineups":    "v_bronze_sofascore_lineups",
    "sofascore/statistics": "v_bronze_sofascore_stats",
    # ESPN: matches and odds have incompatible schemas — separate subdirectories
    "espn/matches":         "v_bronze_espn_matches",
    "espn/odds":            "v_bronze_espn_odds",
    "fbref":                "v_bronze_fbref_stats",   # dir empty; Opta blackout Jan 2026
    "understat":            "v_bronze_understat",
    "club_elo":             "v_bronze_club_elo",
    "reep/people":          "v_bronze_reep_people",
    "reep/teams":           "v_bronze_reep_teams",
    "reep/names":           "v_bronze_reep_names",
}


def refresh_parquet_views(conn: duckdb.DuckDBPyConnection) -> None:
    """
    (Re)create Bronze Parquet views for every source directory that already
    contains at least one .parquet file.

    Call this:
      • From each ingestion script after writing the first file for a source.
      • From init_schema() on startup (skips empty sources silently).
    """
    bronze = Path(settings.parquet_bronze_dir).as_posix()
    created = 0
    for source, view_name in _BRONZE_SOURCES.items():
        source_dir = Path(settings.parquet_bronze_dir) / source
        if any(source_dir.glob("*.parquet")):
            conn.execute(f"""
                CREATE OR REPLACE VIEW {view_name} AS
                SELECT * FROM read_parquet('{bronze}/{source}/*.parquet', union_by_name=true)
            """)
            created += 1
            logger.debug("Parquet view created: %s", view_name)

    total = len(_BRONZE_SOURCES)
    if created:
        logger.info("Parquet views: %d / %d sources available.", created, total)
    else:
        logger.debug("Parquet views deferred — Bronze directories are empty.")


# ---------------------------------------------------------------------------
# Directory bootstrap  (Medallion architecture)
# ---------------------------------------------------------------------------

def _create_parquet_dirs() -> None:
    """Create the bronze / silver / gold Parquet cache directories if absent."""
    dirs = [
        # Bronze — raw, as-fetched from each source
        # Sofascore: 3 subdirectories (events / lineups / statistics — incompatible schemas)
        Path(settings.parquet_bronze_dir) / "sofascore" / "events",
        Path(settings.parquet_bronze_dir) / "sofascore" / "lineups",
        Path(settings.parquet_bronze_dir) / "sofascore" / "statistics",
        Path(settings.parquet_bronze_dir) / "sofascore" / "errors",
        # ESPN: separate subdirectories (matches / odds — incompatible schemas)
        Path(settings.parquet_bronze_dir) / "espn" / "matches",
        Path(settings.parquet_bronze_dir) / "espn" / "odds",
        Path(settings.parquet_bronze_dir) / "espn" / "errors",
        Path(settings.parquet_bronze_dir) / "fbref",       # kept; dir stays empty (Opta blackout)
        Path(settings.parquet_bronze_dir) / "understat",
        Path(settings.parquet_bronze_dir) / "club_elo",
        Path(settings.parquet_bronze_dir) / "reep" / "people",
        Path(settings.parquet_bronze_dir) / "reep" / "teams",
        Path(settings.parquet_bronze_dir) / "reep" / "names",
        # Silver — cleaned, validated, cross-source ID-reconciled
        Path(settings.parquet_silver_dir) / "matches",
        Path(settings.parquet_silver_dir) / "player_stats",
        Path(settings.parquet_silver_dir) / "club_priors",
        # Gold — model outputs (ratings, sim results, dashboard snapshots)
        Path(settings.parquet_gold_dir) / "ratings",
        Path(settings.parquet_gold_dir) / "simulations",
        Path(settings.parquet_gold_dir) / "dashboard",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    logger.info(
        "Parquet directories verified: bronze=%s silver=%s gold=%s",
        settings.parquet_bronze_dir,
        settings.parquet_silver_dir,
        settings.parquet_gold_dir,
    )


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

def init_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """
    Create all tables and Parquet views.  Safe to call on an existing database —
    every statement uses IF NOT EXISTS / CREATE OR REPLACE.
    """
    # Install DuckDB extensions (no-op if already installed)
    for ext in ("json", "httpfs"):
        try:
            conn.execute(f"INSTALL {ext}; LOAD {ext};")
        except Exception as exc:
            logger.warning("Could not load DuckDB extension '%s': %s", ext, exc)

    # Tables
    for ddl in _TABLES:
        conn.execute(ddl)
    logger.info("Schema: %d tables created / verified.", len(_TABLES))

    # Parquet views — created only for sources that already have files.
    # Ingestion scripts call refresh_parquet_views() after their first write.
    refresh_parquet_views(conn)


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s %(message)s",
    )
    _create_parquet_dirs()

    db_path = Path(settings.duckdb_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(str(db_path))
    try:
        init_schema(conn)
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' ORDER BY 1"
        ).fetchall()
        logger.info("Ready. Tables: %s", [t[0] for t in tables])
    finally:
        conn.close()

    logger.info("Database initialised -> %s", db_path.resolve())


if __name__ == "__main__":
    main()
