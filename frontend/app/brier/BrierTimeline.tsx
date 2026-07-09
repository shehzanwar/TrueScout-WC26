"use client"

import {
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  Legend,
} from "recharts"
import type { BrierEntry } from "@/lib/api"

// ---------------------------------------------------------------------------
// Round ordering for sorting matches chronologically
// ---------------------------------------------------------------------------

const ROUND_ORDER: Record<string, number> = {
  "Round of 32": 0,
  "Round of 16": 1,
  "Quarterfinal": 2,
  "Semifinal": 3,
  "Final": 4,
}

function roundOrder(r: string): number {
  for (const [key, v] of Object.entries(ROUND_ORDER)) {
    if (r.toLowerCase().includes(key.toLowerCase().split(" ").slice(-1)[0].toLowerCase())) return v
  }
  if (r.includes("32")) return 0
  if (r.includes("16")) return 1
  if (/quarter/i.test(r)) return 2
  if (/semi/i.test(r)) return 3
  if (/final/i.test(r)) return 4
  return 99
}

interface TimelinePoint {
  idx: number
  label: string
  round: string
  model: number        // cumulative avg brier model
  market: number | null // cumulative avg brier market
  coinFlip: number
}

function buildTimeline(entries: BrierEntry[]): TimelinePoint[] {
  const sorted = [...entries].sort((a, b) => roundOrder(a.round) - roundOrder(b.round))

  let sumModel = 0
  let sumMarket = 0
  let countModel = 0
  let countMarket = 0
  const points: TimelinePoint[] = []

  for (const e of sorted) {
    if (e.brier_model === null) continue
    sumModel += e.brier_model
    countModel++
    if (e.brier_market !== null) {
      sumMarket += e.brier_market
      countMarket++
    }
    points.push({
      idx: countModel,
      label: `${e.home_team.split(" ").slice(-1)[0]} vs ${e.away_team.split(" ").slice(-1)[0]}`,
      round: e.round.replace("Round of ", "R").replace(/Quarterfinals?/, "QF").replace(/Semifinals?/, "SF"),
      model: parseFloat((sumModel / countModel).toFixed(4)),
      market: countMarket > 0 ? parseFloat((sumMarket / countMarket).toFixed(4)) : null,
      coinFlip: 0.25,
    })
  }

  return points
}

// ---------------------------------------------------------------------------
// Custom tooltip
// ---------------------------------------------------------------------------

interface TooltipEntry {
  value: number
  name: string
  color: string
  payload: TimelinePoint
}

function TimelineTooltip({ active, payload }: { active?: boolean; payload?: TooltipEntry[]; label?: string }) {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload as TimelinePoint | undefined
  if (!d) return null

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2.5 text-xs shadow-xl space-y-1">
      <p className="font-semibold text-slate-200">{d.label}</p>
      <p className="text-slate-500">{d.round} · Match #{d.idx}</p>
      <div className="pt-0.5 space-y-0.5">
        <p className="text-sky-400">Model avg: {(d.model * 100).toFixed(2)}</p>
        {d.market !== null && (
          <p className="text-amber-400">Market avg: {(d.market * 100).toFixed(2)}</p>
        )}
        <p className="text-slate-600">Coin flip: 25.00</p>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// BrierTimeline — main export
// ---------------------------------------------------------------------------

export default function BrierTimeline({ entries }: { entries: BrierEntry[] }) {
  const points = buildTimeline(entries)

  if (points.length < 2) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <p className="text-sm font-semibold text-slate-100 mb-1">Accuracy Trend</p>
        <div className="h-32 flex items-center justify-center text-slate-700 text-sm">
          Not enough graded matches yet
        </div>
      </div>
    )
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
      <div className="mb-4">
        <p className="text-sm font-semibold text-slate-100">Accuracy Trend</p>
        <p className="text-xs text-slate-500 mt-0.5">
          Cumulative average Brier score as matches are graded — lower is better · coin flip baseline = 0.25
        </p>
      </div>

      <ResponsiveContainer width="100%" height={220}>
        <ComposedChart data={points} margin={{ top: 8, right: 16, bottom: 24, left: 32 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />

          <XAxis
            dataKey="idx"
            tick={{ fill: "#64748b", fontSize: 10 }}
            label={{ value: "Match #", position: "insideBottom", offset: -10, style: { fill: "#475569", fontSize: 10 } }}
          />
          <YAxis
            domain={[0, 0.3]}
            tickFormatter={(v: number) => v.toFixed(2)}
            tick={{ fill: "#64748b", fontSize: 10 }}
            label={{ value: "Brier score", angle: -90, position: "insideLeft", offset: 16, style: { fill: "#475569", fontSize: 10 } }}
          />

          <ReferenceLine y={0.25} stroke="#334155" strokeDasharray="4 3" strokeWidth={1.5} label={{ value: "Coin flip", position: "right", style: { fill: "#475569", fontSize: 9 } }} />

          <Line
            dataKey="model"
            name="Our model"
            stroke="#38bdf8"
            strokeWidth={2}
            dot={{ r: 3, fill: "#38bdf8", strokeWidth: 0 }}
            activeDot={{ r: 4 }}
            isAnimationActive={false}
          />
          <Line
            dataKey="market"
            name="Bookmakers"
            stroke="#f59e0b"
            strokeWidth={2}
            dot={{ r: 3, fill: "#f59e0b", strokeWidth: 0 }}
            activeDot={{ r: 4 }}
            connectNulls={false}
            isAnimationActive={false}
          />

          <Tooltip content={<TimelineTooltip />} cursor={{ stroke: "#334155" }} />
          <Legend
            verticalAlign="top"
            height={24}
            wrapperStyle={{ fontSize: 11 }}
            formatter={(value, entry) => (
              <span style={{ color: (entry as { color?: string }).color ?? "#94a3b8" }}>{value}</span>
            )}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
