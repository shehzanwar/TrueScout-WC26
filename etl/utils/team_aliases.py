"""
Canonical team-name alias map — shared across ETL modules.

Maps any variant spelling → the canonical Sofascore team name used in
player_ratings and simulation outputs.

Also covers Reep `nationality` / `national_team` variants that differ from the
canonical names used by ESPN and Sofascore (e.g. "Kingdom of the Netherlands").

Imported by:
  etl/models/monte_carlo_sim.py   (_NAME_ALIASES)
  etl/export_json.py              (NAME_ALIASES)
  etl/load/load_national_teams.py (normalise team names from Sofascore lineups)
"""

# ---------------------------------------------------------------------------
# Master alias table
# ---------------------------------------------------------------------------

TEAM_ALIASES: dict[str, str] = {
    # ── ESPN → Sofascore variants ────────────────────────────────────────────
    "Bosnia-Herzegovina":                "Bosnia & Herzegovina",
    "Bosnia and Herzegovina":            "Bosnia & Herzegovina",

    # ── Sofascore / Cape Verde ───────────────────────────────────────────────
    "Cabo Verde":                        "Cape Verde",

    # ── Ivory Coast variants ─────────────────────────────────────────────────
    "Côte d'Ivoire":                     "Ivory Coast",
    "Cote d'Ivoire":                     "Ivory Coast",
    "Cote D'Ivoire":                     "Ivory Coast",

    # ── Congo DR variants (Reep uses long name; ESPN/Sofascore differ) ───────
    "DR Congo":                          "Congo DR",
    "Democratic Republic of Congo":      "Congo DR",
    "Congo, DR":                         "Congo DR",
    "Congo, Democratic Republic":        "Congo DR",
    "Democratic Republic of the Congo":  "Congo DR",

    # ── Netherlands (Reep uses historical long-form) ─────────────────────────
    "Kingdom of the Netherlands":        "Netherlands",
    "Holland":                           "Netherlands",

    # ── England (Reep may record "United Kingdom" for British players) ───────
    "United Kingdom":                    "England",

    # ── South Korea spelling variants ────────────────────────────────────────
    "Korea Republic":                    "South Korea",
    "Republic of Korea":                 "South Korea",

    # ── USA variants ────────────────────────────────────────────────────────
    "USA":                               "United States",
    "United States of America":          "United States",

    # ── Turkey ───────────────────────────────────────────────────────────────
    "Turkey":                            "Türkiye",

    # ── Saudi Arabia ─────────────────────────────────────────────────────────
    "KSA":                               "Saudi Arabia",
    "Kingdom of Saudi Arabia":           "Saudi Arabia",

    # ── Czech Republic ───────────────────────────────────────────────────────
    "Czechia":                           "Czech Republic",
}


def normalize(name: str | None) -> str | None:
    """Map any known team name variant to the canonical form. Returns None → None."""
    if name is None:
        return None
    return TEAM_ALIASES.get(name, name)
