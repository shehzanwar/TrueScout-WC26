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
import type { RadarMetrics, FifaScore } from "@/lib/api"
import { fifaBandColor } from "../FifaBadge"

// Five FM-style attribute axes — fall back to these when radar_axes is absent.
const DEFAULT_AXES: { key: keyof RadarMetrics; label: string; description: string }[] = [
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
    description: "Position-weighted composite percentile",
  },
]

// Axis key order matches the 5-axis radar layout
const AXIS_KEYS: Array<keyof RadarMetrics> = [
  "shooting", "creativity", "defending", "wc_form", "posterior_pct"
]

// Map radar axis index → FIFA attr key (for tooltip sub-attr score)
const AXIS_TO_ATTR_OUTFIELD: string[] = ["SHO", "PAS", "DEF", "WC_FORM", ""]
const AXIS_TO_ATTR_GK: string[]       = ["DIV", "KIC", "HAN", "POS", ""]

interface TooltipPayload {
  payload?: { description: string; attrScore: number | null }
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
      {item.payload?.attrScore != null && (
        <p className="text-slate-300 font-semibold">{item.payload.attrScore}/99</p>
      )}
      <p className="text-slate-400 mt-0.5">{item.payload?.description}</p>
    </div>
  )
}

export default function PlayerRadar({
  radar,
  fifa,
}: {
  radar: RadarMetrics
  fifa?: FifaScore | null
}) {
  // Use position-specific axis labels from the export when available
  const axisLabels       = radar.radar_axes ?? DEFAULT_AXES.map((a) => a.label)
  const axisDescriptions = DEFAULT_AXES.map((a) => a.description)

  // Choose attr key map based on position (GK has DIV/HAN/POS/KIC; outfield has SHO/PAS/DEF/WC_FORM)
  const isGk        = axisLabels[0] === "Shot Stopping"
  const attrKeyMap  = isGk ? AXIS_TO_ATTR_GK : AXIS_TO_ATTR_OUTFIELD

  const data = AXIS_KEYS.map((key, i) => {
    const raw = key === "posterior_pct" ? (radar.overall ?? radar.posterior_pct) : radar[key]
    const value = raw != null ? Math.round((raw as number) * 100) : 0
    const attrKey   = attrKeyMap[i]
    const attrScore = (attrKey && fifa?.attrs?.[attrKey]) ?? null
    return {
      axis:        axisLabels[i] ?? DEFAULT_AXES[i].label,
      value,
      description: axisDescriptions[i],
      attrScore,
    }
  })

  // Radar fill + stroke derived from FIFA band (defaults to emerald when no FIFA data)
  const bandColor = fifa ? fifaBandColor(fifa.band) : "#10b981"

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

      <div className="h-[280px]">
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
              stroke={bandColor}
              fill={bandColor}
              fillOpacity={0.18}
              strokeWidth={2}
              dot={{ fill: bandColor, r: 3, strokeWidth: 0 }}
            />
            <Tooltip content={<CustomTooltip />} />
          </RadarChart>
        </ResponsiveContainer>
      </div>

      {/* Legend — show FIFA sub-attr scores when available */}
      <div className="grid grid-cols-1 gap-1 mt-2 pt-3 border-t border-slate-800">
        {axisLabels.map((label, i) => {
          const attrKey   = attrKeyMap[i]
          // Overall axis (last) uses the composite FIFA overall score; others use per-attr scores
          const attrScore = i === attrKeyMap.length - 1
            ? (fifa?.overall ?? null)
            : (attrKey && fifa?.attrs?.[attrKey]) ?? null
          return (
            <div key={label} className="flex items-baseline gap-2">
              <span className="text-[11px] font-medium text-slate-400 w-24 shrink-0">{label}</span>
              {attrScore != null && (
                <span className="text-[11px] font-bold tabular-nums" style={{ color: bandColor }}>
                  {attrScore}/99
                </span>
              )}
              <span className="text-[11px] text-slate-600">{axisDescriptions[i]}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
