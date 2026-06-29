"use client"

import {
  ComposedChart,
  Scatter,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts"
import type { BrierEntry } from "@/lib/api"
import { getFlag } from "@/lib/flags"

// ---------------------------------------------------------------------------
// Data preparation
// ---------------------------------------------------------------------------

interface ScatterPoint {
  mx: number     // market winner prob (x-axis)
  my: number     // model winner prob  (y-axis)
  label: string  // "Germany vs Belgium"
  winner: string
  round: string
}

function prepareScatter(entries: BrierEntry[]): {
  fav: ScatterPoint[]
  upset: ScatterPoint[]
} {
  const fav: ScatterPoint[] = []
  const upset: ScatterPoint[] = []

  for (const e of entries) {
    if (e.model_prob === null || e.market_prob === null) continue
    const homeWon = e.advanced_team === e.home_team
    const my = homeWon ? e.model_prob : 1 - e.model_prob
    const mx = homeWon ? e.market_prob : 1 - e.market_prob

    const point: ScatterPoint = {
      mx,
      my,
      label: `${e.home_team} vs ${e.away_team}`,
      winner: e.advanced_team,
      round: shortRound(e.round),
    }
    ;(my >= 0.5 ? fav : upset).push(point)
  }

  return { fav, upset }
}

// The diagonal reference line y=x
const REF_LINE: { mx: number; my: number }[] = [
  { mx: 0, my: 0 },
  { mx: 1, my: 1 },
]

function shortRound(r: string): string {
  if (r.includes("32")) return "R32"
  if (r.includes("16")) return "R16"
  if (/quarter/i.test(r)) return "QF"
  if (/semi/i.test(r)) return "SF"
  if (/final/i.test(r) && !/semi|quarter/i.test(r)) return "F"
  return r
}

// ---------------------------------------------------------------------------
// Custom tooltip
// ---------------------------------------------------------------------------

interface TPayload {
  payload?: ScatterPoint
}

function ScatterTooltip({
  active,
  payload,
}: {
  active?: boolean
  payload?: TPayload[]
}) {
  if (!active || !payload?.length || !payload[0].payload) return null
  const d = payload[0].payload
  const modelPct = (d.my * 100).toFixed(1)
  const mktPct = (d.mx * 100).toFixed(1)
  const delta = d.my - d.mx
  const deltaStr = (delta >= 0 ? "+" : "") + (delta * 100).toFixed(1) + "%"
  const deltaColor = delta >= 0 ? "text-emerald-400" : "text-rose-400"

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2.5 text-xs shadow-xl space-y-1.5 min-w-[180px]">
      <p className="font-semibold text-slate-200">
        {getFlag(d.winner)} {d.winner}
      </p>
      <p className="text-slate-500">{d.label} · {d.round}</p>
      <div className="flex justify-between gap-4 pt-0.5">
        <span className="text-emerald-400">Model {modelPct}%</span>
        <span className="text-slate-400">Market {mktPct}%</span>
      </div>
      <p className={`text-[11px] font-medium ${deltaColor}`}>
        Model δ {deltaStr} vs market
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// CalibrationScatter — main export
// ---------------------------------------------------------------------------

export default function CalibrationScatter({ entries }: { entries: BrierEntry[] }) {
  const { fav, upset } = prepareScatter(entries)
  const total = fav.length + upset.length

  if (total === 0) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <p className="text-sm font-semibold text-slate-100 uppercase tracking-wider mb-1">
          Calibration Scatter
        </p>
        <p className="text-xs text-slate-500 mb-6">
          Model probability vs market probability (for the actual winner)
        </p>
        <div className="h-48 flex items-center justify-center text-slate-700 text-sm">
          No matched entries with both model and market data yet.
        </div>
      </div>
    )
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
      <div className="mb-4">
        <p className="text-sm font-semibold text-slate-100 uppercase tracking-wider">
          Calibration Scatter
        </p>
        <p className="text-xs text-slate-500 mt-0.5">
          Each dot = one graded match · dots above the diagonal = model more confident than market
        </p>
      </div>

      <ResponsiveContainer width="100%" height={320}>
        <ComposedChart margin={{ top: 16, right: 24, bottom: 32, left: 24 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />

          <XAxis
            dataKey="mx"
            type="number"
            domain={[0, 1]}
            tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
            tick={{ fill: "#64748b", fontSize: 11 }}
            label={{
              value: "Market probability for winner",
              position: "insideBottom",
              offset: -18,
              style: { fill: "#475569", fontSize: 11 },
            }}
          />
          <YAxis
            dataKey="my"
            type="number"
            domain={[0, 1]}
            tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
            tick={{ fill: "#64748b", fontSize: 11 }}
            label={{
              value: "Model probability for winner",
              angle: -90,
              position: "insideLeft",
              offset: 12,
              style: { fill: "#475569", fontSize: 11 },
            }}
          />

          {/* Diagonal reference line y = x */}
          <Line
            data={REF_LINE}
            dataKey="my"
            type="linear"
            dot={false}
            activeDot={false}
            stroke="#334155"
            strokeDasharray="5 3"
            strokeWidth={1.5}
            legendType="none"
            isAnimationActive={false}
          />

          <Scatter
            name="Favourite won"
            data={fav}
            fill="#10b981"
            fillOpacity={0.8}
            stroke="#059669"
            strokeWidth={1}
            r={5}
          />
          <Scatter
            name="Upset"
            data={upset}
            fill="#f59e0b"
            fillOpacity={0.85}
            stroke="#d97706"
            strokeWidth={1}
            r={5}
          />

          <Tooltip content={<ScatterTooltip />} cursor={{ strokeDasharray: "3 3" }} />
          <Legend
            wrapperStyle={{ fontSize: 11, color: "#64748b", paddingTop: 8 }}
            formatter={(value) => (
              <span style={{ color: "#94a3b8" }}>{value}</span>
            )}
          />
        </ComposedChart>
      </ResponsiveContainer>

      <p className="text-[10px] text-slate-700 text-center mt-1">
        Dashed diagonal = perfect calibration (model = market). {total} matches plotted.
      </p>
    </div>
  )
}
