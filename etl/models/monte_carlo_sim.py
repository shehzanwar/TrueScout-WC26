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
import json
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
from etl.utils.team_aliases import TEAM_ALIASES, normalize as _alias_normalize

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

N_SIM             = 10_000
TOP_N_PLAYERS     = 15
LOGISTIC_SCALE    = 1.5   # P(A wins | delta=+1.0) ≈ 82%; typical match delta ≈ 0.3–0.6
SEED              = 42
FALLBACK_STRENGTH = 7.0   # used when a team has no valid posterior ratings

ROUNDS = ["R32", "R16", "QF", "SF", "F", "W"]

# Keep local reference for direct dict access (used by _R32_SQL glob expansions)
_NAME_ALIASES: dict[str, str] = TEAM_ALIASES


def _normalize(name: str) -> str:
    """Map any known team name variant to the canonical Sofascore name."""
    return _alias_normalize(name) or name


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


def _load_bracket(
    conn: duckdb.DuckDBPyConnection,
) -> tuple[list[str], list[tuple[int, int]]]:
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
    (bracket, r16_pairs)
        bracket   : 32 canonical team names in bracket position order
        r16_pairs : 8 (r32_idx_a, r32_idx_b) tuples using chronological
                    ESPN match indices — i.e. r16_pairs[i] says which two
                    ESPN R32 matches feed R16 slot i.
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

    # Parse each R16 fixture → two R32 match indices (0-based) + n_real (how
    # many sides used an actual team name rather than a placeholder).
    # n_real=2 means both teams are confirmed; n_real=0 means both are TBD.
    r16_pairs_meta: list[tuple[int, int, int]] = []
    for row in r16_df.itertuples(index=False):
        home_n = _parse_r32_num(row.home_team_name)
        away_n = _parse_r32_num(row.away_team_name)
        n_real = 0

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
            n_real += 1
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
            n_real += 1

        r16_pairs_meta.append((home_n - 1, away_n - 1, n_real))  # back to 0-indexed

    # Deduplicate: ESPN occasionally emits BOTH the stale "Round of 32 N Winner"
    # placeholder AND the updated real-team-name entry for the same bracket slot
    # in the same nightly pull (the resolved entry has a higher n_real score).
    # Process entries with MORE real names first (freshest data wins).
    # Indices that get orphaned from skipped stale pairs are repaired by pairing
    # them with the R32 match that would otherwise be absent from the bracket.
    r16_pairs_meta.sort(key=lambda x: -x[2])

    used_r32:  set[int]              = set()
    r16_pairs: list[tuple[int, int]] = []
    orphaned:  list[int]             = []

    for a, b, n_real in r16_pairs_meta:
        a_ok = a not in used_r32
        b_ok = b not in used_r32
        if a_ok and b_ok:
            r16_pairs.append((a, b))
            used_r32.add(a)
            used_r32.add(b)
        elif not a_ok and b_ok:
            orphaned.append(b)
            logger.warning(
                "R16 pair (%d, %d): R32 index %d already used "
                "(ESPN stale placeholder?) — orphaning index %d for repair.",
                a, b, a, b,
            )
        elif a_ok and not b_ok:
            orphaned.append(a)
            logger.warning(
                "R16 pair (%d, %d): R32 index %d already used "
                "(ESPN stale placeholder?) — orphaning index %d for repair.",
                a, b, b, a,
            )
        else:
            logger.warning("R16 pair (%d, %d): both indices already used — discarding.", a, b)

    # Pair each orphaned R32 index with the corresponding missing R32 index
    # so the bracket stays at exactly 32 unique teams.
    #
    # NOTE: orphaned indices are, by construction, always a subset of
    # (all_r32_indices - used_r32) — they were deliberately never added to
    # used_r32. That means an orphaned index always also appears in `missing`.
    # If we zip(orphaned_u, missing) directly, sorted() can place the SAME
    # index at position 0 of both lists, producing a degenerate self-pair
    # (e.g. (3, 3)) that duplicates that match's two teams in the bracket
    # while silently dropping whichever index was the real missing partner.
    # Exclude orphaned indices from the missing-partner pool to prevent this.
    all_r32_indices = set(range(len(r32_fixtures)))
    missing    = sorted(all_r32_indices - used_r32)
    orphaned_u = sorted(set(orphaned) - used_r32)
    missing_partners = sorted(set(missing) - set(orphaned_u))

    if orphaned_u or missing:
        logger.warning(
            "Bracket repair: %d orphaned R32 index(es) %s / "
            "%d missing R32 index(es) %s.",
            len(orphaned_u), orphaned_u, len(missing), missing,
        )
        if len(orphaned_u) != len(missing_partners):
            raise RuntimeError(
                f"Bracket repair imbalance: {len(orphaned_u)} orphaned index(es) "
                f"{orphaned_u} vs {len(missing_partners)} available missing-partner "
                f"index(es) {missing_partners}. Check Bronze R16 fixture data."
            )
        for orph, miss in zip(orphaned_u, missing_partners):
            r16_pairs.append((orph, miss))
            used_r32.add(orph)
            used_r32.add(miss)
            logger.warning("  Paired orphaned R32 %d ↔ missing R32 %d.", orph, miss)

    if len(r16_pairs) != 8:
        raise RuntimeError(
            f"Could only build {len(r16_pairs)}/8 R16 bracket pairs after repair.  "
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
    return bracket, r16_pairs


# ---------------------------------------------------------------------------
# Team strength aggregation (player_ratings via WC lineups)
# ---------------------------------------------------------------------------

def _build_team_strengths(
    conn: duckdb.DuckDBPyConnection,
) -> tuple[dict[str, float], pd.DataFrame]:
    bronze      = Path(settings.parquet_bronze_dir)
    lineup_glob = (bronze / "sofascore" / "lineups" / "*.parquet").as_posix()
    events_glob = (bronze / "sofascore" / "events"  / "*.parquet").as_posix()

    sql = f"""
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
        national_team       AS team,
        AVG(posterior_mean) AS strength,
        COUNT(*)            AS n_players
    FROM ranked
    WHERE rn <= {TOP_N_PLAYERS}
    GROUP BY national_team
    ORDER BY strength DESC
    """

    df = conn.execute(sql).df()
    df["team"] = df["team"].map(_normalize)   # Sofascore Cabo Verde → Cape Verde etc.

    strengths = dict(zip(df["team"], df["strength"].astype(float)))
    logger.info("Strength computed for %d teams (top-%d avg posterior).", len(df), TOP_N_PLAYERS)
    return strengths, df


# ---------------------------------------------------------------------------
# Rest / travel adjustment  (PR5b.1)
# ---------------------------------------------------------------------------

def _compute_rest_adjustments(
    conn: duckdb.DuckDBPyConnection,
    bracket_order: list[str],
) -> dict[str, float]:
    """
    Penalise teams with fewer than 3 rest days before their R32 fixture.

    Formula: delta = -0.10 * max(0, 3 - rest_days)
      0 rest days → -0.30
      1 rest day  → -0.20
      2 rest days → -0.10
      3+ rest days → 0.0 (no penalty)

    Returns {canonical_team_name: strength_delta}.
    Only teams with a non-zero delta are included.
    """
    bronze = Path(settings.parquet_bronze_dir)
    espn_glob = (bronze / "espn" / "matches" / "*.parquet").as_posix()

    try:
        all_df = conn.execute(f"""
            SELECT
                home_team_name, away_team_name,
                CAST(match_date AS DATE) AS match_date,
                round_name
            FROM read_parquet('{espn_glob}', union_by_name=true)
            WHERE match_date IS NOT NULL
        """).df()
    except Exception as exc:
        logger.warning("Rest adjustment: cannot read ESPN matches: %s", exc)
        return {}

    if all_df.empty:
        return {}

    all_df["match_date"] = pd.to_datetime(all_df["match_date"])
    all_df["home_norm"] = all_df["home_team_name"].map(_normalize)
    all_df["away_norm"] = all_df["away_team_name"].map(_normalize)

    # Team → R32 date
    r32_df = all_df[all_df["round_name"] == "Round of 32"]
    team_r32_date: dict[str, pd.Timestamp] = {}
    for _, row in r32_df.iterrows():
        for team in (row["home_norm"], row["away_norm"]):
            if pd.notna(team) and team not in team_r32_date:
                team_r32_date[team] = row["match_date"]

    # Long-form: (team, date) for all non-R32 matches
    pre_rows: list[tuple[str, pd.Timestamp]] = []
    for _, row in all_df[all_df["round_name"] != "Round of 32"].iterrows():
        dt = row["match_date"]
        if pd.notna(row["home_norm"]):
            pre_rows.append((row["home_norm"], dt))
        if pd.notna(row["away_norm"]):
            pre_rows.append((row["away_norm"], dt))

    if not pre_rows:
        logger.info("Rest adjustment: no pre-R32 matches found — skipping.")
        return {}

    hist = pd.DataFrame(pre_rows, columns=["team", "match_date"])

    adjustments: dict[str, float] = {}
    for team in bracket_order:
        r32_date = team_r32_date.get(team)
        if r32_date is None:
            continue
        prev = hist[(hist["team"] == team) & (hist["match_date"] < r32_date)]
        if prev.empty:
            continue
        last_date = prev["match_date"].max()
        rest_days = int((r32_date - last_date).days)
        delta = -0.10 * max(0, 3 - rest_days)
        if delta != 0.0:
            adjustments[team] = delta
            logger.info(
                "Rest adj: %-28s  rest=%dd  delta=%.2f", team, rest_days, delta
            )
        else:
            logger.debug("Rest adj: %-28s  rest=%dd  delta=0.00 (no penalty)", team, rest_days)

    return adjustments


# ---------------------------------------------------------------------------
# Vectorised single-elimination tournament
# ---------------------------------------------------------------------------

def _run_sim(
    strengths: np.ndarray,
    n_sim: int,
    scale: float,
    seed: int,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """
    Pure NumPy vectorised Monte Carlo bracket.

    All n_sim tournaments run simultaneously — no Python loop over iterations.
    One Python loop over the 5 rounds (R32→R16→QF→SF→F→W) is unavoidable.

    Returns
    -------
    advance_counts : (n_teams, n_rounds) int64
        advance_counts[i, r] = # sims where team i reached round r.
        r=0 (R32) = n_sim for all; r=5 (W) = title count.
    slot_winners : dict[round_code → (n_sim, n_slots) int16]
        slot_winners["R32"][:, j] = team index that won R32 match j in each sim.
        slot_winners["R16"][:, j] = team index that won R16 match j in each sim.
        etc.  Used to build the joint bracket-slot distribution for PR4.
    """
    rng     = np.random.default_rng(seed)
    n_teams = len(strengths)
    n_rounds = len(ROUNDS)

    advance_counts = np.zeros((n_teams, n_rounds), dtype=np.int64)
    advance_counts[:, 0] = n_sim   # every team starts in R32

    slot_winners: dict[str, np.ndarray] = {}

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

        # Store who wins each match slot for this round (int16 saves ~50% memory vs int32)
        # ROUNDS[round_idx - 1] is the round whose matches just finished.
        # (round_idx=1 plays R32 matches → slot_winners["R32"])
        slot_winners[ROUNDS[round_idx - 1]] = winners.astype(np.int16)

        flat   = winners.ravel()
        counts = np.bincount(flat, minlength=n_teams)
        advance_counts[:, round_idx] = counts

    return advance_counts, slot_winners


# ---------------------------------------------------------------------------
# Bracket-slot distribution builder  (PR4)
# ---------------------------------------------------------------------------

def _compute_bracket_slots(
    slot_winners: dict[str, np.ndarray],
    bracket_order: list[str],
    n_sim: int,
    run_date: date,
    r16_pairs: list[tuple[int, int]],
) -> dict:
    """
    Convert per-sim slot-winner arrays into a JSON-serialisable distribution.

    For each (round, slot_idx) returns the top team plus up to 2 alternates
    with their probability of winning that specific match slot.  The frontend
    uses this to fix the Colombia-over-Argentina bracket-coherence bug.

    R32 slots are exported using ESPN chronological match indices so they align
    with the matchups API response (r32.matches[j]).  R16+ slots use the
    natural bracket slot indices (already sequential).

    Also exports `pairings` so the frontend can correctly pair R32 matches
    into R16 slots without assuming sequential ESPN order.

    Output shape
    ------------
    {
      "run_date": "2026-06-30",
      "slots": [...],
      "pairings": {
        "R16": [[0,2],[3,5],...],   # ESPN R32 match indices feeding each R16 slot
        "QF":  [[0,1],[2,3],[4,5],[6,7]],
        "SF":  [[0,1],[2,3]],
        "F":   [[0,1]]
      }
    }
    """
    # Map bracket_match_j → espn_match_idx for R32
    # bracket match 2i and 2i+1 come from r16_pairs[i] = (a, b)
    bracket_to_espn: dict[int, int] = {}
    for i, (a, b) in enumerate(r16_pairs):
        bracket_to_espn[2 * i]     = a
        bracket_to_espn[2 * i + 1] = b

    n_teams = len(bracket_order)
    slots: list[dict] = []

    for round_code in ["R32", "R16", "QF", "SF", "F"]:
        sw = slot_winners.get(round_code)
        if sw is None:
            continue
        n_slots = sw.shape[1]
        for slot_j in range(n_slots):
            counts = np.bincount(sw[:, slot_j].astype(np.intp), minlength=n_teams)
            sorted_idx = np.argsort(-counts)
            entries = [
                {"team": bracket_order[int(t)], "prob": round(float(counts[t]) / n_sim, 4)}
                for t in sorted_idx
                if counts[t] > 0
            ]
            if entries:
                # R32: export by ESPN chronological index so the frontend's
                # r32.matches[j] aligns with slotMap["R32:j"] without remapping.
                export_idx = bracket_to_espn.get(slot_j, slot_j) if round_code == "R32" else slot_j
                slots.append({
                    "round":    round_code,
                    "slot_idx": int(export_idx),
                    "top":      entries[0],
                    "alt":      entries[1:3],   # up to 2 alternates
                })

    pairings = {
        "R16": [[a, b] for a, b in r16_pairs],  # ESPN R32 match indices
        "QF":  [[0, 1], [2, 3], [4, 5], [6, 7]],
        "SF":  [[0, 1], [2, 3]],
        "F":   [[0, 1]],
    }

    return {"run_date": str(run_date), "slots": slots, "pairings": pairings}


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
        bracket_order, r16_pairs = _load_bracket(conn)

        # 2. Team strengths from player_ratings
        strengths_map, strength_df = _build_team_strengths(conn)

        # 3. Coverage check — replace any NaN entries (AVG returned NULL when
        #    posterior_mean was all-NaN), then fill teams absent from the map.
        strengths_map = {
            t: (v if np.isfinite(v) else FALLBACK_STRENGTH)
            for t, v in strengths_map.items()
        }

        missing = [t for t in bracket_order if t not in strengths_map]
        if missing:
            valid = [v for v in strengths_map.values() if np.isfinite(v)]
            fallback = float(np.median(valid)) if valid else FALLBACK_STRENGTH
            logger.warning(
                "%d bracket team(s) not in player_ratings — using %.4f: %s",
                len(missing), fallback, missing,
            )
            for t in missing:
                strengths_map[t] = fallback

        # 3c. Rest/travel penalty  (PR5b.1)
        rest_adj = _compute_rest_adjustments(conn, bracket_order)
        if rest_adj:
            for team, delta in rest_adj.items():
                if team in strengths_map:
                    strengths_map[team] = max(1.0, strengths_map[team] + delta)
            logger.info("Applied rest adjustments to %d team(s).", len(rest_adj))
        else:
            logger.info("No rest adjustments applied (3+ rest days for all teams).")

        # 4. Ordered strength vector
        strengths_vec = np.array(
            [strengths_map[t] for t in bracket_order], dtype=np.float64
        )

        # 5. Simulate
        logger.info(
            "Running %d iterations (scale=%.2f, seed=%d) ...",
            args.n_sim, args.scale, args.seed,
        )
        advance_counts, slot_winners = _run_sim(
            strengths=strengths_vec,
            n_sim=args.n_sim,
            scale=args.scale,
            seed=args.seed,
        )
        elapsed = time.perf_counter() - t0
        logger.info("Simulation complete in %.2fs.", elapsed)

        # 6. Build marginal results + bracket slot distributions
        today = date.today()
        results = _build_results(
            bracket_order=bracket_order,
            advance_counts=advance_counts,
            n_sim=args.n_sim,
            run_date=today,
        )
        bracket_slots_data = _compute_bracket_slots(
            slot_winners=slot_winners,
            bracket_order=bracket_order,
            n_sim=args.n_sim,
            run_date=today,
            r16_pairs=r16_pairs,
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
            print("\n=== R16 bracket pairings (R32 ESPN match indices) ===")
            for i, (a, b) in enumerate(r16_pairs):
                print(f"  R16[{i}]: R32[{a}] ({bracket_order[2*i]}) vs R32[{b}] ({bracket_order[2*i+1]})")
            print(f"\n  pairings.R16 = {bracket_slots_data['pairings']['R16']}")
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
            # Write bracket_slots.json to Silver directory (loaded by export_json.py)
            bracket_slots_path = Path(settings.parquet_silver_dir) / "bracket_slots.json"
            bracket_slots_path.write_text(
                json.dumps(bracket_slots_data, ensure_ascii=False), encoding="utf-8"
            )
            logger.info(
                "Done. run_date=%s | %d teams | %d rows written | bracket_slots.json: %d slots.",
                today, len(bracket_order), len(results), len(bracket_slots_data["slots"]),
            )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
