import type { Metadata } from "next"
import { getMatchups, getProjectedQFMatchups } from "@/lib/server-data"
import RoundSelector from "./RoundSelector"
import MatchCardGrid from "./MatchCardGrid"

export const metadata: Metadata = { title: "Matchups" }

const VALID_ROUNDS = new Set(["R32", "R16", "QF", "SF", "F"])

export default async function MatchupsPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>
}) {
  const sp = await searchParams
  const raw = typeof sp.round === "string" ? sp.round.toUpperCase() : "R32"
  const round = VALID_ROUNDS.has(raw) ? raw : "R32"

  let data = await getMatchups(round).catch(() => null)
  let isProjected = false

  // When QF has no ESPN fixtures yet, derive projected matchups from the simulation
  if (round === "QF" && (!data || data.n_matches === 0)) {
    const projected = await getProjectedQFMatchups().catch(() => null)
    if (projected && projected.n_matches > 0) {
      data = projected
      isProjected = true
    }
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-100">Matchups</h1>
        <p className="mt-1 text-sm text-slate-500">
          {data
            ? `${data.n_matches} match${data.n_matches !== 1 ? "es" : ""} · ${data.round_name}`
            : "Knockout round fixtures with model vs market probabilities"}
        </p>
      </div>

      {/* Round tabs */}
      <RoundSelector activeRound={round} />

      {/* Projected banner */}
      {isProjected && (
        <div className="flex items-center gap-2.5 px-4 py-2.5 rounded-lg bg-amber-500/8 border border-amber-500/20 text-xs text-amber-400">
          <svg viewBox="0 0 16 16" fill="currentColor" className="w-3.5 h-3.5 shrink-0">
            <path fillRule="evenodd" d="M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13ZM0 8a8 8 0 1 1 16 0A8 8 0 0 1 0 8Zm8-3.25a.75.75 0 0 1 .75.75v4.5a.75.75 0 0 1-1.5 0v-4.5A.75.75 0 0 1 8 4.75Zm0 7.5a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Z" clipRule="evenodd" />
          </svg>
          <span>
            <span className="font-semibold">Projected</span>
            {" — "}QF fixtures not yet confirmed by ESPN. Teams and odds are derived from the simulation.
            Morocco vs France is confirmed; remaining matchups reflect the most likely bracket path.
          </span>
        </div>
      )}

      {/* Content */}
      {data && data.n_matches > 0 ? (
        <MatchCardGrid matches={data.matches} />
      ) : (
        <div className="py-24 flex flex-col items-center gap-3 text-center">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.5}
            className="w-10 h-10 text-slate-700"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 0 1 2.25-2.25h13.5A2.25 2.25 0 0 1 21 7.5v11.25m-18 0A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75m-18 0v-7.5A2.25 2.25 0 0 1 5.25 9h13.5A2.25 2.25 0 0 1 21 11.25v7.5"
            />
          </svg>
          <p className="text-slate-500 text-sm">No matches scheduled for this round yet.</p>
          <p className="text-slate-700 text-xs">Check back after the group stage concludes.</p>
        </div>
      )}
    </div>
  )
}
