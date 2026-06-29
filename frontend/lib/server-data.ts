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
} from "./api"

function readData<T>(filename: string): T {
  const filePath = path.join(process.cwd(), "public", "data", filename)
  return JSON.parse(readFileSync(filePath, "utf-8")) as T
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

export async function getPlayer(reep_id: string): Promise<PlayerResponse> {
  const players = readData<PlayerResponse[]>("players.json")
  const player = players.find((p) => p.reep_id === reep_id)
  if (!player) throw new Error(`Player not found: ${reep_id}`)
  return player
}
