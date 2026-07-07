import type { BrierEntry } from "@/lib/api"
import { FlagIcon } from "@/app/components/FlagIcon"

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function shortRound(r: string): string {
  if (r.includes("32")) return "R32"
  if (r.includes("16")) return "R16"
  if (/quarter/i.test(r)) return "QF"
  if (/semi/i.test(r)) return "SF"
  if (/final/i.test(r) && !/semi|quarter/i.test(r)) return "F"
  return r
}

interface Call {
  home: string
  away: string
  winner: string
  loser: string
  round: string
  winnerProb: number   // model's probability assigned to the actual winner
}

function deriveCalls(entries: BrierEntry[]): { best: Call | null; miss: Call | null } {
  let best: Call | null = null
  let miss: Call | null = null

  for (const e of entries) {
    if (e.model_prob === null) continue
    const homeWon = e.advanced_team === e.home_team
    const winnerProb = homeWon ? e.model_prob : 1 - e.model_prob
    const loser = homeWon ? e.away_team : e.home_team

    const call: Call = {
      home: e.home_team,
      away: e.away_team,
      winner: e.advanced_team,
      loser,
      round: shortRound(e.round),
      winnerProb,
    }

    // Best call: model was correct (winnerProb > 0.5) and most confident
    if (winnerProb > 0.5 && (!best || winnerProb > best.winnerProb)) best = call
    // Biggest miss: model gave winner the lowest probability
    if (!miss || winnerProb < miss.winnerProb) miss = call
  }

  return { best, miss }
}

// ---------------------------------------------------------------------------
// Card sub-component
// ---------------------------------------------------------------------------

function CallCard({
  type,
  call,
}: {
  type: "best" | "miss"
  call: Call
}) {
  const isBest = type === "best"
  const pct = Math.round(call.winnerProb * 100)

  return (
    <div className={[
      "rounded-lg border px-4 py-3 space-y-2",
      isBest
        ? "bg-emerald-500/5 border-emerald-500/20"
        : "bg-rose-500/5 border-rose-500/20",
    ].join(" ")}>
      <div className="flex items-center justify-between">
        <span className={`text-[10px] font-semibold uppercase tracking-wider ${isBest ? "text-emerald-500" : "text-rose-500"}`}>
          {isBest ? "Best call" : "Biggest miss"}
        </span>
        <span className="text-[10px] text-slate-600">{call.round}</span>
      </div>

      {/* Match line */}
      <p className="text-xs text-slate-400">
        <span className="text-slate-300 font-medium">{call.home}</span>
        <span className="text-slate-600 mx-1.5">vs</span>
        <span className="text-slate-300 font-medium">{call.away}</span>
      </p>

      {/* Result */}
      <div className="flex items-center gap-1.5">
        <FlagIcon name={call.winner} size={13} />
        <span className="text-sm font-semibold text-slate-100">{call.winner} advanced</span>
      </div>

      {/* Probability callout */}
      <p className={`text-xs ${isBest ? "text-emerald-400" : "text-rose-400"}`}>
        Model gave {call.winner}{" "}
        <span className="font-semibold tabular-nums">{pct}%</span>
        {isBest ? " — and they delivered." : " — they advanced anyway."}
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// BiggestCalls — main export
// ---------------------------------------------------------------------------

export default function BiggestCalls({ entries }: { entries: BrierEntry[] }) {
  const { best, miss } = deriveCalls(entries)

  if (!best && !miss) return null

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
      <div>
        <p className="text-sm font-semibold text-slate-100 uppercase tracking-wider">
          Biggest Calls
        </p>
        <p className="text-xs text-slate-500 mt-0.5">
          Most confident correct pick · Biggest upset miss
        </p>
      </div>

      <div className="space-y-3">
        {best && <CallCard type="best" call={best} />}
        {miss && <CallCard type="miss" call={miss} />}
      </div>
    </div>
  )
}
