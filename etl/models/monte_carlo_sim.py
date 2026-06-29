"""
Monte Carlo bracket simulation for the 2026 World Cup knockout stage.

10,000 vectorised iterations of a 32-team single-elimination bracket.

Bracket construction — data-driven (no hardcoding):
  1. Read the 16 actual R32 fixtures from Bronze ESPN matches
     (round_name = 'Round of 32', fetched via espn_pull --knockout).
  2. Read the 8 R16 fixtures to derive the bracket pairing tree
     (the R16 entries contain "Round of 32 N Winner" placeholders that
     encode which R32 match numbers meet in each R16 slot).
  3. Arrange all 32 teams in bracket positions such that:
       - adjacent pairs (2k, 2k+1) play each other in R32
       - winners of adjacent R32-pairs fight in R16 (mirroring the real draw)
       - the full QF / SF / Final tree follows from standard elimination

Team strength = mean posterior_mean of the top-15 rated players per team
                (player_ratings joined to WC Sofascore lineups via identity_players).
Match winner  = logistic strength-delta:
                  P(A wins) = 1 / (1 + 10^(-(sA - sB) / SCALE))

NO Dixon-Coles, NO fatigue, NO injuries.

Writes 192 rows (32 teams × 6 rounds) to the ``simulations`` table:
    run_date, round, team_id (canonical ESPN name), advance_prob,
    title_prob, n_iterations

Bronze prerequisites
--------------------
    python -m etl.sources.espn_pull --knockout   # adds R32+R16 fixture Parquets

Usage
-----
    python -m etl.models.monte_carlo_sim
    python -m etl.models.monte_carlo_sim --validate   # dry-run, no DB write
    python -m etl.models.monte_carlo_sim --scale 2.0
"""
import argparse
import logging
import re
import sys
import time
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

N_SIM          = 10_000
TOP_N_PLAYERS  = 15
LOGISTIC_SCALE = 1.5   # P(A wins | delta=+1.0) ≈ 82%; typical match delta ≈ 0.3–0.6
SEED           = 42

ROUNDS = ["R32", "R16", "QF", "SF", "F", "W"]

# ---------------------------------------------------------------------------
# Team name normalisation
#
# ESPN and Sofascore use different spellings for several national teams.
# This dict maps ANY variant → the canonical name used in player_ratings
# (which comes from Sofascore event home_team_name / away_team_name).
# ---------------------------------------------------------------------------

_NAME_ALIASES: dict[str, str] = {
    # ESPN → Sofascore variants
    "Bosnia-Herzegovina":           "Bosnia & Herzegovina",
    "Bosnia and Herzegovina":       "Bosnia & Herzegovina",
    # Sofascore → canonical (already canonical)
    "Cabo Verde":                   "Cape Verde",
    # Fallback variants
    "Côte d'Ivoire":                "Ivory Coast",
    "Cote d'Ivoire":                "Ivory Coast",
    "DR Congo":                     "Congo DR",
    "Democratic Republic of Congo": "Congo DR",
    "Congo, DR":                    "Congo DR",
    "USA":                          "United States",
}


def _normalize(name: str) -> str:
    """Map any known team name variant to the canonical Sofascore name."""
    return _NAME_ALIASES.get(name, name)


# ---------------------------------------------------------------------------
# Bracket construction from Bronze
# ---------------------------------------------------------------------------

_R32_SQL = """
SELECT home_team_name, away_team_name, match_date, event_id
FROM read_parquet('{glob}', union_by_name=true)
WHERE round_name = 'Round of 32'
ORDER BY match_date, CAST(event_id AS BIGINT)
"""

_R16_SQL = """
SELECT home_team_name, away_team_name, match_date, event_id
FROM read_parquet('{glob}', union_by_name=true)
WHERE round_name = 'Round of 16'
ORDER BY match_date, CAST(event_id AS BIGINT)
"""

_R32_MATCH_RE = re.compile(r"Round of 32 (\d+) Winner", re.IGNORECASE)


def _parse_r32_num(name: str) -> int | None:
    """
    Extract N from ESPN placeholder 'Round of 32 N Winner' (1-indexed).
    Returns None if the string is an actual team name (already resolved).
    """
    m = _R32_MATCH_RE.search(name)
    return int(m.group(1)) if m else None


def _load_bracket(conn: duckdb.DuckDBPyConnection) -> list[str]:
    """
    Build the 32-slot bracket position list from Bronze ESPN fixture data.

    Algorithm
    ---------
    1. Load R32 fixtures (chronological) → r32[0..15] = (home, away)
       ESPN numbers them 1-16 in this same order.

    2. Build reverse map: canonical_team_name → r32_match_index (0-based).

    3. Load R16 fixtures (chronological).  Each R16 entry names two R32
       match numbers via 'Round of 32 N Winner' placeholders (or an actual
       team name if that R32 match is already complete).

    4. The 8 R16 pairs give us the bracket pairing structure:
         r16_pair[i] = (r32_idx_A, r32_idx_B)
       Adjacent R16 pairs (i and i+1) feed into the same QF.

    5. Arrange bracket positions:
         positions 0,1 = r32_pair[0].A.home, r32_pair[0].A.away
         positions 2,3 = r32_pair[0].B.home, r32_pair[0].B.away
         positions 4,5 = r32_pair[1].A.home, r32_pair[1].A.away
         ...
       This makes standard adjacent-pair simulation correctly model the draw.

    Returns
    -------
    List of 32 canonical team names in bracket position order.
    """
    bronze = Path(settings.parquet_bronze_dir)
    espn_glob = (bronze / "espn" / "matches" / "*.parquet").as_posix()

    try:
        r32_df = conn.execute(_R32_SQL.format(glob=espn_glob)).df()
        r16_df = conn.execute(_R16_SQL.format(glob=espn_glob)).df()
    except Exception as exc:
        raise RuntimeError(
            f"Cannot load R32/R16 fixture data from Bronze: {exc}\n"
            "Run: python -m etl.sources.espn_pull --knockout"
        ) from exc

    if len(r32_df) != 16:
        raise RuntimeError(
            f"Expected 16 R32 fixtures in Bronze, found {len(r32_df)}. "
            "Run: python -m etl.sources.espn_pull --knockout"
        )
    if len(r16_df) != 8:
        raise RuntimeError(
            f"Expected 8 R16 fixtures in Bronze, found {len(r16_df)}. "
            "Run: python -m etl.sources.espn_pull --knockout"
        )

    # r32_fixtures[i] = (home_canonical, away_canonical)  0-indexed
    r32_fixtures = [
        (_normalize(row.home_team_name), _normalize(row.away_team_name))
        for row in r32_df.itertuples(index=False)
    ]

    # team → 0-based R32 match index (for resolving actual team names in R16)
    team_to_r32_idx: dict[str, int] = {}
    for idx, (home, away) in enumerate(r32_fixtures):
        team_to_r32_idx[home] = idx
        team_to_r32_idx[away] = idx

    # Parse each R16 fixture → two R32 match indices (0-based)
    r16_pairs: list[tuple[int, int]] = []
    for row in r16_df.itertuples(index=False):
        home_n = _parse_r32_num(row.home_team_name)
        away_n = _parse_r32_num(row.away_team_name)

        # If the R32 match is already complete, ESPN shows the real team name
        if home_n is None:
            team = _normalize(row.home_team_name)
            home_n = team_to_r32_idx.get(team)
            if home_n is None:
                logger.warning(
                    "Cannot resolve R16 home '%s' to an R32 match — skipping pair.",
                    row.home_team_name,
                )
                continue
            home_n += 1  # convert to 1-indexed to keep uniform
        if away_n is None:
            team = _normalize(row.away_team_name)
            away_n = team_to_r32_idx.get(team)
            if away_n is None:
                logger.warning(
                    "Cannot resolve R16 away '%s' to an R32 match — skipping pair.",
                    row.away_team_name,
                )
                continue
            away_n += 1

        r16_pairs.append((home_n - 1, away_n - 1))  # back to 0-indexed

    if len(r16_pairs) != 8:
        raise RuntimeError(
            f"Could only parse {len(r16_pairs)}/8 R16 bracket pairs.  "
            "Check Bronze R16 fixture data."
        )

    # Build bracket positions: for each R16 pair (a, b) in order, place
    # r32_fixtures[a] then r32_fixtures[b] as consecutive 4-slot sections.
    bracket: list[str] = []
    for a, b in r16_pairs:
        home_a, away_a = r32_fixtures[a]
        home_b, away_b = r32_fixtures[b]
        bracket.extend([home_a, away_a, home_b, away_b])

    assert len(bracket) == 32, f"Bracket has {len(bracket)} slots, expected 32"
    assert len(set(bracket)) == 32, f"Duplicate teams in bracket: {sorted(bracket)}"

    logger.info("Bracket loaded from Bronze (16 R32 + 8 R16 fixtures).")
    return bracket


# ---------------------------------------------------------------------------
# Team strength aggregation (player_ratings via WC lineups)
# ---------------------------------------------------------------------------

_STRENGTH_SQL = """
WITH wc_players AS (
    SELECT DISTINCT
        CAST(l.player_id AS VARCHAR) AS sofascore_id,
        CASE l.team_side
            WHEN 'home' THEN e.home_team_name
            WHEN 'away' THEN e.away_team_name
        END AS national_team
    FROM read_parquet('{lineup_glob}', union_by_name=true) l
    JOIN read_parquet('{events_glob}', union_by_name=true) e
      ON CAST(l.event_id AS BIGINT) = CAST(e.event_id AS BIGINT)
),
player_national AS (
    SELECT
        wc.national_team,
        ip.reep_id,
        pr.posterior_mean
    FROM wc_players wc
    JOIN identity_players ip ON wc.sofascore_id = ip.key_sofascore
    JOIN player_ratings   pr ON ip.reep_id       = pr.reep_id
),
ranked AS (
    SELECT
        national_team,
        posterior_mean,
        ROW_NUMBER() OVER (
            PARTITION BY national_team
            ORDER BY posterior_mean DESC
        ) AS rn
    FROM player_national
)
SELECT
    national_team                AS team,
    AVG(posterior_mean)          AS strength,
    COUNT(*)                     AS n_players
FROM ranked
WHERE rn <= {top_n}
GROUP BY national_team
ORDER BY strength DESC
"""


def _build_team_strengths(
    conn: duckdb.DuckDBPyConnection,
) -> tuple[dict[str, float], pd.DataFrame]:
    bronze      = Path(settings.parquet_bronze_dir)
    lineup_glob = (bronze / "sofascore" / "lineups" / "*.parquet").as_posix()
    events_glob = (bronze / "sofascore" / "events"  / "*.parquet").as_posix()

    sql = _STRENGTH_SQL.format(
        lineup_glob=lineup_glob,
        events_glob=events_glob,
        top_n=TOP_N_PLAYERS,
    )
    df = conn.execute(sql).df()
    df["team"] = df["team"].map(_normalize)   # Sofascore Cabo Verde → Cape Verde etc.

    strengths = dict(zip(df["team"], df["strength"].astype(float)))
    logger.info("Strength computed for %d teams (top-%d avg posterior).",
                len(df), TOP_N_PLAYERS)
    return strengths, df


# ---------------------------------------------------------------------------
# Vectorised single-elimination tournament
# ---------------------------------------------------------------------------

def _run_sim(
    strengths: np.ndarray,
    n_sim: int,
    scale: float,
    seed: int,
) -> np.ndarray:
    """
    Pure NumPy vectorised Monte Carlo bracket.

    All n_sim tournaments run simultaneously — no Python loop over iterations.
    One Python loop over the 5 rounds (R32→R16→QF→SF→F→W) is unavoidable.

    Returns
    -------
    advance_counts : (n_teams, n_rounds) int64
        advance_counts[i, r] = # sims where team i reached round r.
        r=0 (R32) = n_sim for all; r=5 (W) = title count.
    """
    rng     = np.random.default_rng(seed)
    n_teams = len(strengths)
    n_rounds = len(ROUNDS)

    advance_counts = np.zeros((n_teams, n_rounds), dtype=np.int64)
    advance_counts[:, 0] = n_sim   # every team starts in R32

    # current[sim, bracket_pos] = team index at that position
    current = np.broadcast_to(
        np.arange(n_teams, dtype=np.int32), (n_sim, n_teams)
    ).copy()

    for round_idx in range(1, n_rounds):
        n_alive  = current.shape[1]
        n_matches = n_alive // 2

        left  = current[:, 0::2]    # (n_sim, n_matches)
        right = current[:, 1::2]

        s_left  = strengths[left]   # NumPy fancy indexing → same shape
        s_right = strengths[right]

        p_left = 1.0 / (1.0 + np.power(10.0, -(s_left - s_right) / scale))
        rand   = rng.random((n_sim, n_matches))

        winners = np.where(rand < p_left, left, right)
        current = winners

        flat   = winners.ravel()
        counts = np.bincount(flat, minlength=n_teams)
        advance_counts[:, round_idx] = counts

    return advance_counts


# ---------------------------------------------------------------------------
# Build results DataFrame
# ---------------------------------------------------------------------------

def _build_results(
    bracket_order: list[str],
    advance_counts: np.ndarray,
    n_sim: int,
    run_date: date,
) -> pd.DataFrame:
    title_counts = advance_counts[:, -1]
    rows: list[dict] = []
    for pos, team in enumerate(bracket_order):
        tp = float(title_counts[pos] / n_sim)
        for r_idx, rnd in enumerate(ROUNDS):
            rows.append({
                "run_date":     run_date,
                "round":        rnd,
                "team_id":      team,
                "advance_prob": float(advance_counts[pos, r_idx] / n_sim),
                "title_prob":   tp,
                "n_iterations": n_sim,
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# DuckDB write
# ---------------------------------------------------------------------------

def _write_simulations(conn: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> None:
    today = str(df["run_date"].iloc[0])
    conn.execute("DELETE FROM simulations WHERE run_date = ?", [today])
    conn.register("_sim_results", df)
    conn.execute("""
        INSERT INTO simulations
        SELECT run_date, round, team_id, advance_prob, title_prob, n_iterations
        FROM _sim_results
    """)
    conn.unregister("_sim_results")
    n_total = conn.execute("SELECT COUNT(*) FROM simulations").fetchone()[0]
    logger.info("simulations: %d rows total after upsert.", n_total)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate(
    bracket_order: list[str],
    results: pd.DataFrame,
    strengths_map: dict[str, float],
) -> None:
    # Print actual R32 matchups so the user can verify against the real bracket
    logger.info("=== R32 matchups being simulated ===")
    for i in range(0, 32, 2):
        home = bracket_order[i]
        away = bracket_order[i + 1]
        sh = strengths_map.get(home, float("nan"))
        sa = strengths_map.get(away, float("nan"))
        logger.info("  M%02d: %-28s (%.3f) vs %-28s (%.3f)", i // 2 + 1, home, sh, away, sa)

    title_rows = (
        results[results["round"] == "W"][["team_id", "title_prob"]]
        .sort_values("title_prob", ascending=False)
    )
    logger.info("=== Top-10 title probabilities ===")
    for _, row in title_rows.head(10).iterrows():
        logger.info("  %-28s  %.1f%%", row["team_id"], row["title_prob"] * 100)

    total = title_rows["title_prob"].sum()
    logger.info("Title prob sum = %.6f (expect 1.0)", total)
    if abs(total - 1.0) > 0.02:
        raise RuntimeError(f"Title probs sum to {total:.4f} — check simulation logic.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Monte Carlo WC bracket sim.")
    parser.add_argument("--validate", action="store_true",
                        help="Dry-run: print results but skip DB write.")
    parser.add_argument("--scale",  type=float, default=LOGISTIC_SCALE)
    parser.add_argument("--n-sim",  type=int,   default=N_SIM)
    parser.add_argument("--seed",   type=int,   default=SEED)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")

    conn = duckdb.connect(str(settings.duckdb_path), read_only=args.validate)

    try:
        t0 = time.perf_counter()

        # 1. Load actual bracket from Bronze
        bracket_order = _load_bracket(conn)

        # 2. Team strengths from player_ratings
        strengths_map, strength_df = _build_team_strengths(conn)

        # 3. Coverage check — missing teams get the median strength
        missing = [t for t in bracket_order if t not in strengths_map]
        if missing:
            fallback = float(np.median(list(strengths_map.values())))
            logger.warning(
                "%d bracket team(s) not in player_ratings — using median %.4f: %s",
                len(missing), fallback, missing,
            )
            for t in missing:
                strengths_map[t] = fallback

        # 4. Ordered strength vector
        strengths_vec = np.array(
            [strengths_map[t] for t in bracket_order], dtype=np.float64
        )

        # 5. Simulate
        logger.info(
            "Running %d iterations (scale=%.2f, seed=%d) ...",
            args.n_sim, args.scale, args.seed,
        )
        advance_counts = _run_sim(
            strengths=strengths_vec,
            n_sim=args.n_sim,
            scale=args.scale,
            seed=args.seed,
        )
        elapsed = time.perf_counter() - t0
        logger.info("Simulation complete in %.2fs.", elapsed)

        # 6. Build results
        results = _build_results(
            bracket_order=bracket_order,
            advance_counts=advance_counts,
            n_sim=args.n_sim,
            run_date=date.today(),
        )

        # 7. Validate
        _validate(bracket_order, results, strengths_map)

        # 8. Write or print
        if args.validate:
            logger.info("--validate: skipping DB write.")
            print("\n=== Strength table (bracket teams only) ===")
            bracket_strength = strength_df[
                strength_df["team"].isin(bracket_order)
            ].sort_values("strength", ascending=False)
            print(bracket_strength.to_string(index=False))
            print("\n=== Advance probabilities by round ===")
            pivot = (
                results.pivot(index="team_id", columns="round", values="advance_prob")
                [ROUNDS]
                .sort_values("W", ascending=False)
            )
            pivot.columns.name = None
            print(pivot.round(3).to_string())
        else:
            _write_simulations(conn, results)
            logger.info(
                "Done. run_date=%s | %d teams | %d rows written.",
                date.today(), len(bracket_order), len(results),
            )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
