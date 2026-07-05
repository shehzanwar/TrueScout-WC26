/**
 * Server-only data fetchers — reads static JSON files from public/data/.
 *
 * Only import this module from Server Components (page.tsx, layout.tsx).
 * Client Components must use the functions in lib/api.ts instead.
 *
 * Files are written nightly by etl/export_json.py and committed to git,
 * so Vercel serves them as static assets via its CDN.
 */
import { readFileSync } from "fs"
import path from "path"
import type {
  SimulationsResponse,
  MatchupsResponse,
  BrierResponse,
  PlayerResponse,
  InsightsResponse,
} from "./api"
import { nationSlug } from "./api"

// ---------------------------------------------------------------------------
// Nation types
// ---------------------------------------------------------------------------

export type NationMatch = {
  round: string
  event_id: string
  match_date: string
  opponent: string
  isHome: boolean
  teamScore: number | null
  oppScore: number | null
  winner: string | null
  completed: boolean
}

export type NationSummary = {
  name: string
  slug: string
  title_prob: number
  eliminated: boolean
  current_round: string
}

export type NationDetail = NationSummary & {
  sim_rounds: { round: string; advance_prob: number; title_prob: number }[]
  matches: NationMatch[]
  squad: PlayerResponse[]
}

const KNOCKOUT_ROUNDS = ["R32", "R16", "QF", "SF", "F"] as const

function nationSlugs(name: string): string {
  return name
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/&/g, "and")
    .replace(/[^a-z0-9\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
}

function readData<T>(filename: string): T {
  const filePath = path.join(process.cwd(), "public", "data", filename)
  return JSON.parse(readFileSync(filePath, "utf-8")) as T
}

function readDataOrNull<T>(filename: string): T | null {
  try {
    return readData<T>(filename)
  } catch {
    return null
  }
}

export async function getSimulations(): Promise<SimulationsResponse> {
  return readData<SimulationsResponse>("simulations.json")
}

export async function getMatchups(round = "R32"): Promise<MatchupsResponse> {
  const all = readData<Record<string, MatchupsResponse>>("matchups.json")
  return (
    all[round] ?? {
      round_code: round,
      round_name: round,
      n_matches: 0,
      matches: [],
    }
  )
}

export async function getBrier(): Promise<BrierResponse> {
  return readData<BrierResponse>("brier.json")
}

function slugify(name: string): string {
  return name
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
}

export async function getPlayer(idOrSlug: string): Promise<PlayerResponse> {
  const players = readData<PlayerResponse[]>("players.json")
  // Prefer exact reep_id match (fast path)
  let player = players.find((p) => p.reep_id === idOrSlug)
  // Fall back to slug — use pre-computed slug when present, derive from name otherwise
  if (!player) {
    player = players.find(
      (p) => (p.slug ?? (p.name ? slugify(p.name) : null)) === idOrSlug
    )
  }
  if (!player) throw new Error(`Player not found: ${idOrSlug}`)
  return player
}

export async function getAllMatchups(): Promise<Record<string, MatchupsResponse>> {
  return readData<Record<string, MatchupsResponse>>("matchups.json")
}

// Derives projected QF matchups from simulations.json when ESPN has not yet
// published QF fixtures. Uses bracket pairings + R16/QF bracket_slot probs.
export async function getProjectedQFMatchups(): Promise<MatchupsResponse | null> {
  const sim = readDataOrNull<SimulationsResponse>("simulations.json")
  if (!sim?.pairings?.QF?.length || !sim.bracket_slots?.length) return null

  type SlotEntry = { round: string; slot_idx: number; top: { team: string; prob: number } }
  const slotMap = new Map<string, SlotEntry>()
  for (const e of sim.bracket_slots as SlotEntry[]) {
    slotMap.set(`${e.round}:${e.slot_idx}`, e)
  }

  // Top projected winner for each R16 slot
  const r16Top = new Map<number, string>()
  for (const e of sim.bracket_slots as SlotEntry[]) {
    if (e.round === "R16") r16Top.set(e.slot_idx, e.top.team)
  }

  // Track which R16 slots are confirmed (prob === 1.0 means the winner is locked in)
  const r16Confirmed = new Set<number>()
  for (const e of sim.bracket_slots as SlotEntry[]) {
    if (e.round === "R16" && e.top.prob === 1.0) r16Confirmed.add(e.slot_idx)
  }

  const matches = sim.pairings.QF.map(([slotA, slotB], qfIdx) => {
    const homeTeam = r16Top.get(slotA) ?? `R16[${slotA}] Winner`
    const awayTeam = r16Top.get(slotB) ?? `R16[${slotB}] Winner`
    const bothConfirmed = r16Confirmed.has(slotA) && r16Confirmed.has(slotB)

    // Only show QF slot probabilities when both competing teams are confirmed R16 winners.
    // For projected slots, the slot prob bundles multiple possible opponents and is misleading
    // as a head-to-head probability.
    const qfSlot = bothConfirmed ? slotMap.get(`QF:${qfIdx}`) : null
    let homeProb: number | null = null
    if (qfSlot) {
      homeProb = qfSlot.top.team === homeTeam ? qfSlot.top.prob : 1 - qfSlot.top.prob
    }

    return {
      event_id: `proj-QF-${qfIdx}`,
      match_date: "TBD",
      round: "Quarterfinals",
      is_completed: false,
      venue: null,
      winner: null,
      home: {
        name: homeTeam,
        abbrev: null,
        score: null,
        model_advance_prob: homeProb,
        market_advance_prob: null,
        rest_days: null,
        travel_km: null,
      },
      away: {
        name: awayTeam,
        abbrev: null,
        score: null,
        model_advance_prob: homeProb !== null ? 1 - homeProb : null,
        market_advance_prob: null,
        rest_days: null,
        travel_km: null,
      },
    }
  })

  return {
    round_code: "QF",
    round_name: "Quarterfinals",
    n_matches: matches.length,
    matches,
  }
}

export async function getTopPlayers(
  limit = 5,
  minConfidence = 0.5,
): Promise<PlayerResponse[]> {
  const players = readData<PlayerResponse[]>("players.json")

  // Build the set of teams still active in the tournament (title_prob > 0).
  // Eliminates group-stage exits (e.g. Turkey) that would otherwise rank highly
  // due to strong Bayesian priors with no R32+ minutes to update them down.
  const sims = readDataOrNull<SimulationsResponse>("simulations.json")
  const activeTeams = new Set<string>()
  if (sims) {
    for (const rnd of sims.rounds) {
      for (const t of rnd.teams) {
        if (t.title_prob > 0) activeTeams.add(t.team_id)
      }
    }
  }

  return players
    .filter(
      (p) =>
        p.confidence_score >= minConfidence &&
        (activeTeams.size === 0 ||
          activeTeams.has(p.national_team ?? "") ||
          activeTeams.has(p.nationality ?? "")),
    )
    .sort((a, b) => b.posterior_mean - a.posterior_mean)
    .slice(0, limit)
}

export async function getInsights(): Promise<InsightsResponse | null> {
  return readDataOrNull<InsightsResponse>("insights.json")
}

// ---------------------------------------------------------------------------
// Nations — derived from simulations + matchups + players
// ---------------------------------------------------------------------------

function buildNationSummaries(): NationSummary[] {
  const sims = readDataOrNull<SimulationsResponse>("simulations.json")
  const allMatchups = readDataOrNull<Record<string, MatchupsResponse>>("matchups.json")
  if (!sims) return []

  // R32 teams: every team that appears in any simulation round
  const teamSet = new Set<string>()
  const titleProbMap = new Map<string, number>()
  const advanceProbMap = new Map<string, Map<string, number>>()

  for (const rnd of sims.rounds) {
    for (const t of rnd.teams) {
      teamSet.add(t.team_id)
      if (!titleProbMap.has(t.team_id) || rnd.round === "R32") {
        titleProbMap.set(t.team_id, t.title_prob)
      }
      if (!advanceProbMap.has(t.team_id)) advanceProbMap.set(t.team_id, new Map())
      advanceProbMap.get(t.team_id)!.set(rnd.round, t.advance_prob)
    }
  }

  // Determine the highest round each team appeared in matchups
  const lastRoundMap = new Map<string, string>()
  if (allMatchups) {
    for (const round of KNOCKOUT_ROUNDS) {
      const rnd = allMatchups[round]
      if (!rnd) continue
      for (const m of rnd.matches) {
        if (teamSet.has(m.home.name)) lastRoundMap.set(m.home.name, round)
        if (teamSet.has(m.away.name)) lastRoundMap.set(m.away.name, round)
      }
    }
  }

  return Array.from(teamSet).map((name) => {
    const tp = titleProbMap.get(name) ?? 0
    return {
      name,
      slug: nationSlugs(name),
      title_prob: tp,
      eliminated: tp === 0,
      current_round: lastRoundMap.get(name) ?? "R32",
    }
  })
}

export async function getAllNations(): Promise<NationSummary[]> {
  return buildNationSummaries()
}

export async function getNationDetail(slug: string): Promise<NationDetail | null> {
  const summaries = buildNationSummaries()
  const summary = summaries.find((n) => n.slug === slug)
  if (!summary) return null

  const name = summary.name
  const sims = readDataOrNull<SimulationsResponse>("simulations.json")
  const allMatchups = readDataOrNull<Record<string, MatchupsResponse>>("matchups.json")
  const allPlayers = readDataOrNull<PlayerResponse[]>("players.json")

  // Sim rounds: what does the model say for each round?
  const sim_rounds: NationDetail["sim_rounds"] = []
  if (sims) {
    for (const rnd of sims.rounds) {
      const entry = rnd.teams.find((t) => t.team_id === name)
      if (entry) {
        sim_rounds.push({ round: rnd.round, advance_prob: entry.advance_prob, title_prob: entry.title_prob })
      }
    }
  }

  // Matches: all rounds where this team appears
  const matches: NationMatch[] = []
  if (allMatchups) {
    for (const round of KNOCKOUT_ROUNDS) {
      const rnd = allMatchups[round]
      if (!rnd) continue
      for (const m of rnd.matches) {
        const isHome = m.home.name === name
        const isAway = m.away.name === name
        if (!isHome && !isAway) continue
        const opponent = isHome ? m.away.name : m.home.name
        const teamScore = isHome ? m.home.score : m.away.score
        const oppScore  = isHome ? m.away.score : m.home.score
        matches.push({
          round,
          event_id: m.event_id,
          match_date: m.match_date,
          opponent,
          isHome,
          teamScore: teamScore ?? null,
          oppScore:  oppScore ?? null,
          winner: m.winner ?? null,
          completed: m.is_completed,
        })
      }
    }
  }

  // Squad: players who represented this nation at the WC
  const squad = (allPlayers ?? [])
    .filter((p) => (p.national_team ?? p.nationality) === name && (p.wc_minutes ?? 0) > 0)
    .sort((a, b) => b.posterior_mean - a.posterior_mean)

  return { ...summary, sim_rounds, matches, squad }
}

export async function getNationSlugs(): Promise<string[]> {
  const summaries = buildNationSummaries()
  return summaries.map((n) => n.slug)
}

export async function getSimilarPlayers(
  player: PlayerResponse,
  limit = 4,
): Promise<PlayerResponse[]> {
  const all = readData<PlayerResponse[]>("players.json")

  // Prefer same K-Means cluster (scoped to position_bucket) — tightest match
  const hasMeaningfulCluster = player.cluster_id !== -1 && player.cluster_id != null
  let pool: PlayerResponse[] = []

  if (hasMeaningfulCluster) {
    pool = all.filter(
      (p) =>
        p.reep_id !== player.reep_id &&
        p.position_bucket === player.position_bucket &&
        p.cluster_id === player.cluster_id &&
        p.wc_minutes > 0,
    )
  }

  // Fallback: same positional micro-role (e.g. all LWs, all CFs)
  if (pool.length < 2) {
    pool = all.filter(
      (p) =>
        p.reep_id !== player.reep_id &&
        p.wc_minutes > 0 &&
        (player.position_micro
          ? p.position_micro === player.position_micro
          : p.position_bucket === player.position_bucket),
    )
  }

  return pool
    .sort((a, b) => b.posterior_mean - a.posterior_mean)
    .slice(0, limit)
}
