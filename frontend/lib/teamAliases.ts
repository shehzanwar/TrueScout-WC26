/**
 * Canonical team-name alias map — mirrors etl/utils/team_aliases.py.
 *
 * Maps any variant spelling → the canonical Sofascore team name used in
 * simulations.json and players.json (national_team field).
 *
 * Used in MatchCard.tsx to normalise team names for lineup filtering.
 */

export const TEAM_ALIASES: Record<string, string> = {
  // ESPN → Sofascore
  "Bosnia-Herzegovina":               "Bosnia & Herzegovina",
  "Bosnia and Herzegovina":           "Bosnia & Herzegovina",
  // Sofascore
  "Cabo Verde":                       "Cape Verde",
  // Ivory Coast
  "Côte d'Ivoire":                    "Ivory Coast",
  "Cote d'Ivoire":                    "Ivory Coast",
  "Cote D'Ivoire":                    "Ivory Coast",
  // Congo DR
  "DR Congo":                         "Congo DR",
  "Democratic Republic of Congo":     "Congo DR",
  "Congo, DR":                        "Congo DR",
  "Congo, Democratic Republic":       "Congo DR",
  "Democratic Republic of the Congo": "Congo DR",
  // Netherlands
  "Kingdom of the Netherlands":       "Netherlands",
  "Holland":                          "Netherlands",
  // England
  "United Kingdom":                   "England",
  // South Korea
  "Korea Republic":                   "South Korea",
  "Republic of Korea":                "South Korea",
  // USA
  "USA":                              "United States",
  "United States of America":         "United States",
  // Turkey
  "Turkey":                           "Türkiye",
  // Saudi Arabia
  "KSA":                              "Saudi Arabia",
  "Kingdom of Saudi Arabia":          "Saudi Arabia",
  // Czech Republic
  "Czechia":                          "Czech Republic",
}

/** Normalise any team name to the canonical form used across the app. */
export function normalizeTeam(name: string | null | undefined): string | null {
  if (!name) return null
  return TEAM_ALIASES[name] ?? name
}
