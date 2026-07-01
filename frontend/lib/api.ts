// ---------------------------------------------------------------------------
// Types — mirror the shape of every static JSON file / Pydantic model exactly
// ---------------------------------------------------------------------------

export interface SimTeam {
  team_id: string
  advance_prob: number
  title_prob: number
}

export interface SimRound {
  round: string        // "R32" | "R16" | "QF" | "SF" | "F" | "W"
  round_label: string  // "Round of 32" | … | "Champion"
  teams: SimTeam[]
}

// Per-slot joint distribution entry — written by monte_carlo_sim.py (PR4)
export interface BracketSlotTeam {
  team: string
  prob: number
}

export interface BracketSlotEntry {
  round: string      // "R32" | "R16" | "QF" | "SF" | "F"
  slot_idx: number   // 0-based match index within the round
  top: BracketSlotTeam
  alt: BracketSlotTeam[]
}

export interface SimulationsResponse {
  run_date: string
  n_iterations: number
  rounds: SimRound[]
  bracket_slots?: BracketSlotEntry[]  // absent until PR4 pipeline runs
  pairings?: Record<string, [number, number][]>  // R16/QF/SF/F slot pairings
}

export interface MatchupTeam {
  name: string
  abbrev: string | null
  score: number | null
  model_advance_prob: number | null
  market_advance_prob: number | null
  rest_days: number | null
  travel_km: number | null
}

export interface Matchup {
  event_id: string
  match_date: string
  round: string
  is_completed: boolean
  venue?: string | null
  winner?: string | null
  home: MatchupTeam
  away: MatchupTeam
}

export interface MatchupsResponse {
  round_code: string
  round_name: string
  n_matches: number
  matches: Matchup[]
}

export interface BrierEntry {
  event_id: string
  run_date: string
  round: string
  home_team: string
  away_team: string
  advanced_team: string
  model_prob: number | null
  market_prob: number | null
  brier_model: number | null
  brier_market: number | null
  log_loss_model: number | null
  log_loss_market: number | null
}

export interface BrierSummary {
  n_matches: number
  n_with_market: number
  avg_brier_model: number | null
  avg_brier_market: number | null
  avg_log_loss_model: number | null
  avg_log_loss_market: number | null
  coin_flip_brier: number
  coin_flip_log_loss: number
  brier_skill_vs_coin: number | null
  brier_skill_vs_market: number | null
}

export interface BrierResponse {
  summary: BrierSummary
  entries: BrierEntry[]
}

// FIFA-style 0-99 dual display (PR6)
export interface FifaAttrs {
  // Outfield: SHO, PAS, DEF, WC_FORM
  // GK:       DIV, HAN, POS, KIC
  [key: string]: number | null
}

export interface FifaScore {
  overall: number | null
  band: string
  attrs: FifaAttrs
}

export interface RadarMetrics {
  // FM-style attribute percentiles (0.0–1.0 within position group)
  shooting:   number | null   // goals, xG, shots per-90 (GKs: shot-stopping)
  creativity: number | null   // xA, key passes, assists per-90
  defending:  number | null   // tackles, interceptions, clearances per-90
  wc_form:    number | null   // Sofascore WC rating percentile
  // Position-aware composite — replaces posterior_pct on the radar chart (PR 3)
  overall?:   number | null   // weighted combination per position group
  // Position-specific axis labels (5 items matching radar order)
  radar_axes?: string[]
  // Bayesian dimensions (used by the stats info card, not the radar chart)
  posterior_pct: number
  wc_experience: number
  confidence: number
  prior_pct: number
  wc_dominance: number
}

// Per-match entry — populated by PR3 ETL export
export interface MatchLogEntry {
  match_date: string
  opponent: string
  opponent_code: string
  score: string
  minutes: number
  rating: number
  adjusted_rating?: number
  goals: number
  assists: number
  xg: number
  xa: number
  shots: number
  key_passes: number
  tackles: number
  interceptions: number
  yellow_card: boolean
}

export interface PlayerResponse {
  reep_id: string
  name: string | null
  nationality: string | null
  national_team: string | null   // derived from Sofascore lineups — authoritative team membership
  age_at_wc: number | null        // age on 2026-06-11 (tournament start)
  age_cohort: "u21" | "22-26" | "27-31" | "32+" | null
  position_detail: string | null
  position_macro: string           // always present (GK/DEF/MID/FWD)
  position_micro: string | null
  cluster_id: number               // always present
  cluster_label: string | null
  position_bucket: string          // always present
  // Bayesian posterior — always present for players in player_ratings
  prior_mean: number
  posterior_mean: number
  posterior_std: number
  hdi_low: number
  hdi_high: number
  shrinkage_weight: number
  wc_minutes: number
  confidence_score: number
  percentile_rank: number
  radar: RadarMetrics
  // Optional fields added by PR3 ETL export
  wc_matches?: number
  wc_goals_raw?: number
  wc_assists_raw?: number
  wc_xg_raw?: number
  wc_xa_raw?: number
  wc_shots_raw?: number
  wc_sot_raw?: number
  wc_key_passes_raw?: number
  wc_tackles_raw?: number
  wc_interceptions_raw?: number
  wc_clearances_raw?: number
  wc_saves_raw?: number
  wc_goals_per_90?: number
  wc_assists_per_90?: number
  wc_xg_per_90?: number
  wc_xa_per_90?: number
  wc_shots_per_90?: number
  wc_sot_per_90?: number
  wc_key_passes_per_90?: number
  wc_tackles_per_90?: number
  wc_interceptions_per_90?: number
  wc_clearances_per_90?: number
  wc_saves_per_90?: number
  wc_passes_completed_raw?: number
  wc_passes_attempted_raw?: number
  wc_passes_completed_per_90?: number
  wc_pass_completion_pct?: number
  has_prior?: boolean
  prior_goals_per_90?: number
  prior_assists_per_90?: number
  prior_xg_per_90?: number
  prior_xa_per_90?: number
  prior_shots_per_90?: number
  prior_key_passes_per_90?: number
  match_log?: MatchLogEntry[]
  position_source?: string
  fifa?: FifaScore
}

export interface PlayerSearchResult {
  reep_id: string
  name: string | null
  nationality: string | null
  national_team: string | null
  position_micro: string | null
  position_macro: string
  posterior_mean: number
  confidence_score: number
  percentile_rank: number
  fifa?: { overall: number | null; band: string }
}

export interface NarrativeResponse {
  narrative: string
  voice: "data_analyst" | "traditional_scout"
  model?: string
}

export interface InsightsFavorite {
  team: string
  title_prob: number | null
}

export interface InsightsValuePick {
  event_id: string
  match_date: string
  home: string | null
  away: string | null
  model_home: number
  market_home: number
  edge: number
}

export interface InsightsPerformer {
  reep_id: string
  name: string | null
  national_team: string | null
  position: string | null
  rating: number | null
}

export interface InsightsOvernight {
  team: string
  delta: number
  title_prob: number
}

export interface InsightsResponse {
  generated_at: string
  run_date: string
  top_favorites: InsightsFavorite[]
  value_picks: InsightsValuePick[]
  next_match: { event_id: string; match_date: string; home: string | null; away: string | null } | null
  top_performers: InsightsPerformer[]
  overnight: InsightsOvernight[]
}

// ---------------------------------------------------------------------------
// Search helpers
// ---------------------------------------------------------------------------

/**
 * Strip diacritics and lowercase — lets users type "Mbappe" and match "Mbappé",
 * "Vinicius" and match "Vinícius", etc.
 */
export function normalizeString(str: string): string {
  return str
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
}

// ---------------------------------------------------------------------------
// Client-side fetchers (safe to call from browser Client Components)
// ---------------------------------------------------------------------------

/**
 * Search players by name substring against the locally cached players.json.
 * The JSON (~2 MB) is downloaded once and browser-cached; subsequent calls
 * are served from the HTTP cache — no RTT beyond the first search per session.
 *
 * Search is accent-insensitive: "Mbappe" matches "Mbappé".
 * Results are sorted by confidence_score then posterior_mean so global
 * superstars (Messi, Ronaldo, Mbappé) always surface above lesser-known
 * namesakes.
 */
export async function searchPlayers(q: string): Promise<PlayerSearchResult[]> {
  if (q.trim().length < 2) return []

  const res = await fetch("/data/players.json", { cache: "force-cache" })
  if (!res.ok) throw new Error("Failed to fetch player data")
  const players = (await res.json()) as PlayerResponse[]

  const query = normalizeString(q.trim())
  return players
    .filter((p) => normalizeString(p.name ?? "").includes(query))
    .sort(
      (a, b) =>
        b.confidence_score - a.confidence_score ||
        b.posterior_mean - a.posterior_mean
    )
    .slice(0, 20)
    .map((p) => ({
      reep_id:          p.reep_id,
      name:             p.name,
      nationality:      p.nationality,
      national_team:    p.national_team ?? null,
      position_micro:   p.position_micro,
      position_macro:   p.position_macro,
      posterior_mean:   p.posterior_mean,
      confidence_score: p.confidence_score,
      percentile_rank:  p.percentile_rank,
      fifa:             p.fifa ? { overall: p.fifa.overall, band: p.fifa.band } : undefined,
    }))
}

/**
 * Generate a confidence-gated scouting narrative via the Next.js API route,
 * which proxies to OpenRouter server-side (API key never touches the browser).
 * Timeout: 30 s — LLM calls can be slow on the free tier.
 */
export async function generateNarrative(reep_id: string): Promise<NarrativeResponse> {
  const controller = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => { timedOut = true; controller.abort() }, 54_000)
  try {
    const res = await fetch(`/api/narratives/${encodeURIComponent(reep_id)}`, {
      method: "POST",
      cache: "no-store",
      signal: controller.signal,
    })
    if (!res.ok) {
      const body = await res.json().catch(() => null) as { error?: string } | null
      throw new Error(body?.error ?? `Error ${res.status}`)
    }
    return res.json() as Promise<NarrativeResponse>
  } catch (err) {
    if (controller.signal.aborted) {
      throw new Error(
        timedOut
          ? "The AI model is busy — it took too long. Try again in a moment."
          : "Request cancelled."
      )
    }
    throw err
  } finally {
    clearTimeout(timer)
  }
}
