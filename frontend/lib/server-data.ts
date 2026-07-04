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
