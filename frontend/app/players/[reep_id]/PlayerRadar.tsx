"use client"

import {
  RadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
  Tooltip,
} from "recharts"
import type { RadarMetrics } from "@/lib/api"

// Five FM-style attribute axes — readable by any football fan.
const AXES: { key: keyof RadarMetrics; label: string; description: string }[] = [
  {
    key: "shooting",
    label: "Shooting",
    description: "Goals, xG & shots per 90 — within position group",
  },
  {
    key: "creativity",
    label: "Playmaking",
    description: "xA, key passes & assists per 90 — within position group",
  },
  {
    key: "defending",
    label: "Defending",
    description: "Tackles, interceptions & clearances per 90",
  },
  {
    key: "wc_form",
    label: "WC Form",
    description: "Sofascore tournament rating — within position group",
  },
  {
    key: "posterior_pct",
    label: "Overall",
    description: "TrueScout Rating percentile within position group",
  },
]

interface TooltipPayload {
  payload?: { description: string }
  value?: number
}

function CustomTooltip({
  active,
  payload,
}: {
  active?: boolean
  payload?: TooltipPayload[]
}) {
  if (!active || !payload?.length) return null
  const item = payload[0]
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs shadow-xl">
      <p className="text-emerald-400 font-bold">{item.value}th percentile</p>
      <p className="text-slate-400 mt-0.5">{item.payload?.description}</p>
    </div>
  )
}

export default function PlayerRadar({ radar }: { radar: RadarMetrics }) {
  const data = AXES.map(({ key, label, description }) => {
    const raw = radar[key]
    // null / undefined → 0 so the chart doesn't break; shown as a collapsed spoke.
    const value = raw != null ? Math.round(raw * 100) : 0
    return { axis: label, value, description }
  })

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 flex flex-col">
      <div className="mb-1">
        <h2 className="text-sm font-semibold text-slate-100 uppercase tracking-wider">
          Attribute Radar
        </h2>
        <p className="text-xs text-slate-500 mt-0.5">
          Percentile within position group · 0 – 100
        </p>
      </div>

      <div className="flex-1 min-h-[240px]">
        <ResponsiveContainer width="100%" height="100%">
          <RadarChart data={data} cx="50%" cy="50%" outerRadius="68%">
            <PolarGrid stroke="#334155" strokeOpacity={0.7} />
            <PolarAngleAxis
              dataKey="axis"
              tick={{ fill: "#94a3b8", fontSize: 11, fontFamily: "inherit" }}
            />
            <PolarRadiusAxis
              angle={90}
              domain={[0, 100]}
              tick={false}
              axisLine={false}
            />
            <Radar
              name="Player"
              dataKey="value"
              stroke="#10b981"
              fill="#10b981"
              fillOpacity={0.18}
              strokeWidth={2}
              dot={{ fill: "#10b981", r: 3, strokeWidth: 0 }}
            />
            <Tooltip content={<CustomTooltip />} />
          </RadarChart>
        </ResponsiveContainer>
      </div>

      {/* Legend */}
      <div className="grid grid-cols-1 gap-1 mt-2 pt-3 border-t border-slate-800">
        {AXES.map(({ label, description }) => (
          <div key={label} className="flex items-baseline gap-2">
            <span className="text-[11px] font-medium text-slate-400 w-20 shrink-0">{label}</span>
            <span className="text-[11px] text-slate-600">{description}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
