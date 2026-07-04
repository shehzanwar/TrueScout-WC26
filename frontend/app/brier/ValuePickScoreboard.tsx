import type { BrierEntry } from "@/lib/api"
import { FlagIcon } from "@/app/components/FlagIcon"

// ---------------------------------------------------------------------------
// Types + helpers
// ---------------------------------------------------------------------------

const EDGE_THRESHOLD = 0.10   // model must be ≥10pp above market to qualify

interface ValuePick {
  entry:       BrierEntry
  backedTeam:  string
  edgePct:     number    // absolute edge in percentage points
  correct:     boolean
  brierDelta:  number | null  // brier_market − brier_model (positive = model won)
  round:       string
}

const ROUND_ORDER: Record<string, number> = { R32: 0, R16: 1, QF: 2, SF: 3, F: 4 }

function shortRound(r: string): string {
  if (r.includes("32")) return "R32"
  if (r.includes("16")) return "R16"
  if (/quarter/i.test(r)) return "QF"
  if (/semi/i.test(r)) return "SF"
  if (/final/i.test(r) && !/semi|quarter/i.test(r)) return "F"
  return r
}

function extractPicks(entries: BrierEntry[]): ValuePick[] {
  const picks: ValuePick[] = []

  for (const e of entries) {
    if (e.model_prob === null || e.market_prob === null) continue
    const edge = e.model_prob - e.market_prob   // positive = model favours home more than market

    if (Math.abs(edge) < EDGE_THRESHOLD) continue

    const backedTeam = edge > 0 ? e.home_team : e.away_team
    const edgePct    = Math.abs(edge)
    const correct    = e.advanced_team === backedTeam
    const brierDelta =
      e.brier_model !== null && e.brier_market !== null
        ? e.brier_market - e.brier_model
        : null

    picks.push({
      entry: e,
      backedTeam,
      edgePct,
      correct,
      brierDelta,
      round: shortRound(e.round),
    })
  }

  return picks.sort(
    (a, b) => (ROUND_ORDER[a.round] ?? 9) - (ROUND_ORDER[b.round] ?? 9),
  )
}

// ---------------------------------------------------------------------------
// ValuePickScoreboard
// ---------------------------------------------------------------------------

export default function ValuePickScoreboard({ entries }: { entries: BrierEntry[] }) {
  const picks = extractPicks(entries)

  const nCorrect = picks.filter(p => p.correct).length
  const brierDeltas = picks.map(p => p.brierDelta).filter((v): v is number => v !== null)
  const avgDelta = brierDeltas.length
    ? brierDeltas.reduce((s, v) => s + v, 0) / brierDeltas.length
    : null
  const cumulativeDelta = brierDeltas.length
    ? brierDeltas.reduce((s, v) => s + v, 0)
    : null

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">

      {/* Header */}
      <div className="px-5 pt-5 pb-3 border-b border-slate-800">
        <p className="text-sm font-semibold text-slate-100 uppercase tracking-wider">
          Value Pick Scoreboard
        </p>
        <p className="text-xs text-slate-500 mt-0.5">
          Matches where our model gave ≥10pp more probability than the market · wins and losses both shown
        </p>

        {picks.length > 0 && (
          <div className="flex flex-wrap gap-x-5 gap-y-1 mt-3 text-xs">
            <span className="text-slate-400">
              <span className="text-slate-200 font-semibold tabular-nums">{nCorrect}/{picks.length}</span>
              {" "}correct
            </span>
            {avgDelta !== null && (
              <span className="text-slate-400">
                avg Δ Brier{" "}
                <span className={`font-semibold tabular-nums ${avgDelta > 0 ? "text-emerald-400" : "text-rose-400"}`}>
                  {avgDelta > 0 ? "+" : ""}{avgDelta.toFixed(4)}
                </span>
                {" "}vs market
              </span>
            )}
            {cumulativeDelta !== null && (
              <span className="text-slate-400">
                cumulative Δ{" "}
                <span className={`font-semibold tabular-nums ${cumulativeDelta > 0 ? "text-emerald-400" : "text-rose-400"}`}>
                  {cumulativeDelta > 0 ? "+" : ""}{cumulativeDelta.toFixed(4)}
                </span>
              </span>
            )}
          </div>
        )}
      </div>

      {/* Body */}
      {picks.length === 0 ? (
        <div className="px-5 py-8 text-center text-xs text-slate-600">
          No significant edges called yet — threshold is model ≥10pp above market.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[540px]">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-950/50">
                {["Round", "Match", "Model backed", "Edge", "Result", "Δ Brier"].map((h, i) => (
                  <th
                    key={h}
                    className={`px-3 py-2.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500
                      ${i >= 3 ? "text-right" : "text-left"}`}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/50">
              {picks.map(pick => {
                const { entry: e } = pick
                const deltaStr = pick.brierDelta !== null
                  ? (pick.brierDelta > 0 ? "+" : "") + pick.brierDelta.toFixed(4)
                  : "—"
                const deltaColor = pick.brierDelta === null
                  ? "text-slate-600"
                  : pick.brierDelta > 0.005
                    ? "text-emerald-400"
                    : pick.brierDelta < -0.005
                      ? "text-rose-400"
                      : "text-slate-400"

                return (
                  <tr
                    key={e.event_id}
                    className={`text-xs transition-colors border-l-2 ${
                      pick.correct
                        ? "bg-emerald-500/5 border-emerald-500/40"
                        : "bg-rose-500/5 border-rose-500/30"
                    }`}
                  >
                    <td className="px-3 py-3 text-slate-400 font-medium whitespace-nowrap">
                      {pick.round}
                    </td>
                    <td className="px-3 py-3 text-slate-400 whitespace-nowrap">
                      <FlagIcon name={e.home_team} size={12} />
                      {" "}{e.home_team}
                      <span className="mx-1 text-slate-700">vs</span>
                      <FlagIcon name={e.away_team} size={12} />
                      {" "}{e.away_team}
                    </td>
                    <td className="px-3 py-3 text-slate-200 font-medium whitespace-nowrap">
                      <FlagIcon name={pick.backedTeam} size={12} />
                      {" "}{pick.backedTeam}
                    </td>
                    <td className="px-3 py-3 text-right text-emerald-400 font-semibold tabular-nums whitespace-nowrap">
                      +{(pick.edgePct * 100).toFixed(1)}pp
                    </td>
                    <td className="px-3 py-3 text-right whitespace-nowrap">
                      {pick.correct ? (
                        <span className="text-emerald-400 font-semibold">✓ Correct</span>
                      ) : (
                        <span className="text-rose-400 font-semibold">✗ Wrong</span>
                      )}
                    </td>
                    <td className={`px-3 py-3 text-right font-mono tabular-nums whitespace-nowrap ${deltaColor}`}>
                      {deltaStr}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="px-5 py-3 border-t border-slate-800 text-[10px] text-slate-700">
        Δ Brier = market_brier − model_brier · positive = model did better than market on that pick · threshold: |model − market| ≥ 10pp
      </div>
    </div>
  )
}
