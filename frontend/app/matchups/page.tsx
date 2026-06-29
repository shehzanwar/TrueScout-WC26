import { getMatchups } from "@/lib/server-data"
import RoundSelector from "./RoundSelector"
import MatchCardGrid from "./MatchCardGrid"

const VALID_ROUNDS = new Set(["R32", "R16", "QF", "SF", "F"])

export default async function MatchupsPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>
}) {
  const sp = await searchParams
  const raw = typeof sp.round === "string" ? sp.round.toUpperCase() : "R32"
  const round = VALID_ROUNDS.has(raw) ? raw : "R32"

  const data = await getMatchups(round).catch(() => null)

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
