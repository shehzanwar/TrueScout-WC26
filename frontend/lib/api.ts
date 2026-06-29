const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1"

// ---------------------------------------------------------------------------
// Types — mirroring Pydantic response models exactly
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

export interface SimulationsResponse {
  run_date: string
  n_iterations: number
  rounds: SimRound[]
}

export interface MatchupTeam {
  name: string
  abbrev: string | null
  score: number | null
  model_advance_prob: number | null
  market_advance_prob: number | null
}

export interface Matchup {
  event_id: string
  match_date: string
  round: string
  is_completed: boolean
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

export interface RadarMetrics {
  posterior_pct: number   // percentile_rank
  wc_experience: number   // min(wc_minutes / 270, 1.0)
  confidence: number      // confidence_score
  prior_pct: number       // PERCENT_RANK of prior_mean within position_macro
  wc_dominance: number    // 1 – shrinkage_weight
}

export interface PlayerResponse {
  reep_id: string
  name: string
  nationality: string | null
  position_detail: string | null
  position_macro: string | null
  position_micro: string | null
  cluster_id: number | null
  cluster_label: string | null
  position_bucket: string | null
  prior_mean: number | null
  posterior_mean: number | null
  posterior_std: number | null
  hdi_low: number | null
  hdi_high: number | null
  shrinkage_weight: number | null
  wc_minutes: number | null
  confidence_score: number | null
  percentile_rank: number | null
  radar: RadarMetrics
}

// ---------------------------------------------------------------------------
// Fetchers
// ---------------------------------------------------------------------------

async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    // No caching — always fresh from the Python backend
    cache: "no-store",
  })
  if (!res.ok) {
    throw new Error(`API error ${res.status} on ${path}`)
  }
  return res.json() as Promise<T>
}

export async function getSimulations(): Promise<SimulationsResponse> {
  return apiFetch<SimulationsResponse>("/simulations/")
}

export async function getMatchups(round = "R32"): Promise<MatchupsResponse> {
  return apiFetch<MatchupsResponse>(`/matchups/?round=${round}`)
}

export async function getBrier(): Promise<BrierResponse> {
  return apiFetch<BrierResponse>("/brier/")
}

export async function getPlayer(reep_id: string): Promise<PlayerResponse> {
  return apiFetch<PlayerResponse>(`/players/${reep_id}`)
}
