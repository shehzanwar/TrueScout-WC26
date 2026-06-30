"use client"

import { useState } from "react"
import { motion } from "framer-motion"
import type { PlayerResponse } from "@/lib/api"

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmt(v: number | undefined | null, decimals = 2): string {
  if (v === undefined || v === null || isNaN(v)) return "—"
  return v.toFixed(decimals)
}

function posGroupLabel(macro: string): string {
  switch (macro) {
    case "GK":  return "goalkeepers"
    case "DEF": return "defenders"
    case "MID": return "midfielders"
    case "FWD": return "forwards"
    default:    return "players"
  }
}

function comparator(pct: number | null | undefined, group: string): string | undefined {
  if (pct == null) return undefined
  if (pct >= 0.50) {
    return `Top ${Math.max(1, Math.round((1 - pct) * 100))}% of ${group}`
  }
  return `Bottom ${Math.max(1, Math.round(pct * 100))}% of ${group}`
}

// ---------------------------------------------------------------------------
// StatTile
// ---------------------------------------------------------------------------

const tileVariants = {
  hidden: { opacity: 0, y: 6 },
  show: { opacity: 1, y: 0, transition: { duration: 0.2, ease: "easeOut" as const } },
}

function StatTile({
  label,
  totalVal,
  per90Val,
  comp,
  showPer90,
}: {
  label: string
  totalVal: string
  per90Val: string
  comp?: string
  showPer90: boolean
}) {
  const main = showPer90 ? per90Val : totalVal
  const sub  = showPer90
    ? (totalVal !== "—" ? `${totalVal} total` : undefined)
    : (per90Val !== "—" ? `${per90Val} /90` : undefined)

  return (
    <motion.div variants={tileVariants} className="space-y-0.5">
      <p className="text-[10px] text-slate-600 uppercase tracking-wider truncate">{label}</p>
      <p className="text-sm font-bold text-slate-100 tabular-nums">{main}</p>
      {sub && <p className="text-[10px] text-slate-500">{sub}</p>}
      {comp && <p className="text-[10px] text-emerald-500">{comp}</p>}
    </motion.div>
  )
}

const gridVariants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.04 } },
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

export default function RawStats({ player }: { player: PlayerResponse }) {
  const [showPer90, setShowPer90] = useState(false)

  const hasWC    = (player.wc_minutes ?? 0) > 0
  const hasPrior = player.has_prior ?? false
  const isGK     = player.position_macro === "GK"
  const group    = posGroupLabel(player.position_macro)

  if (!hasWC && !hasPrior) return null

  return (
    <div className="space-y-4">
      {/* ── World Cup so far ─────────────────────────────────────────── */}
      {hasWC && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-sm font-semibold text-slate-100 uppercase tracking-wider">
                World Cup so far
              </h2>
              <p className="text-xs text-slate-500 mt-0.5">
                {player.wc_matches != null
                  ? `${player.wc_matches} appearance${player.wc_matches !== 1 ? "s" : ""}`
                  : "Performance data"}
                {" · "}{Math.round(player.wc_minutes ?? 0)} min
              </p>
            </div>
            <button
              onClick={() => setShowPer90((v) => !v)}
              className={[
                "text-[10px] uppercase tracking-wider px-2.5 py-1 rounded-full border transition-colors",
                showPer90
                  ? "border-emerald-500/40 text-emerald-400 bg-emerald-500/5"
                  : "border-slate-700 text-slate-500 hover:text-slate-300 hover:border-slate-600",
              ].join(" ")}
            >
              {showPer90 ? "Per 90" : "Totals"}
            </button>
          </div>

          <motion.div
            key={showPer90 ? "per90" : "totals"}
            variants={gridVariants}
            initial="hidden"
            animate="show"
            className="grid grid-cols-3 sm:grid-cols-4 gap-x-4 gap-y-4"
          >
            <StatTile
              label="Minutes"
              totalVal={Math.round(player.wc_minutes ?? 0).toString()}
              per90Val="—"
              showPer90={showPer90}
            />
            <StatTile
              label="Goals"
              totalVal={fmt(player.wc_goals_raw, 0)}
              per90Val={fmt(player.wc_goals_per_90)}
              comp={comparator(player.radar?.shooting, group)}
              showPer90={showPer90}
            />
            <StatTile
              label="Assists"
              totalVal={fmt(player.wc_assists_raw, 0)}
              per90Val={fmt(player.wc_assists_per_90)}
              comp={comparator(player.radar?.creativity, group)}
              showPer90={showPer90}
            />
            <StatTile
              label="xG"
              totalVal={fmt(player.wc_xg_raw)}
              per90Val={fmt(player.wc_xg_per_90)}
              showPer90={showPer90}
            />
            <StatTile
              label="xA"
              totalVal={fmt(player.wc_xa_raw)}
              per90Val={fmt(player.wc_xa_per_90)}
              showPer90={showPer90}
            />
            {!isGK && (
              <>
                <StatTile
                  label="Shots"
                  totalVal={fmt(player.wc_shots_raw, 0)}
                  per90Val={fmt(player.wc_shots_per_90)}
                  showPer90={showPer90}
                />
                <StatTile
                  label="Shots on target"
                  totalVal={fmt(player.wc_sot_raw, 0)}
                  per90Val={fmt(player.wc_sot_per_90)}
                  showPer90={showPer90}
                />
                <StatTile
                  label="Key passes"
                  totalVal={fmt(player.wc_key_passes_raw, 0)}
                  per90Val={fmt(player.wc_key_passes_per_90)}
                  showPer90={showPer90}
                />
                <StatTile
                  label="Tackles"
                  totalVal={fmt(player.wc_tackles_raw, 0)}
                  per90Val={fmt(player.wc_tackles_per_90)}
                  comp={
                    player.position_macro !== "FWD"
                      ? comparator(player.radar?.defending, group)
                      : undefined
                  }
                  showPer90={showPer90}
                />
                <StatTile
                  label="Interceptions"
                  totalVal={fmt(player.wc_interceptions_raw, 0)}
                  per90Val={fmt(player.wc_interceptions_per_90)}
                  showPer90={showPer90}
                />
                <StatTile
                  label="Clearances"
                  totalVal={fmt(player.wc_clearances_raw, 0)}
                  per90Val={fmt(player.wc_clearances_per_90)}
                  showPer90={showPer90}
                />
              </>
            )}
            {isGK && (
              <StatTile
                label="Saves"
                totalVal={fmt(player.wc_saves_raw, 0)}
                per90Val={fmt(player.wc_saves_per_90)}
                comp={comparator(player.radar?.defending, group)}
                showPer90={showPer90}
              />
            )}
          </motion.div>
        </div>
      )}

      {/* ── Last 2 club seasons ──────────────────────────────────────── */}
      {hasPrior && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="mb-4">
            <h2 className="text-sm font-semibold text-slate-100 uppercase tracking-wider">
              Last 2 club seasons
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">Per 90 averages · Understat</p>
          </div>

          <motion.div
            variants={gridVariants}
            initial="hidden"
            animate="show"
            className="grid grid-cols-3 sm:grid-cols-4 gap-x-4 gap-y-4"
          >
            <StatTile
              label="Goals /90"
              totalVal={fmt(player.prior_goals_per_90)}
              per90Val="—"
              showPer90={false}
            />
            <StatTile
              label="Assists /90"
              totalVal={fmt(player.prior_assists_per_90)}
              per90Val="—"
              showPer90={false}
            />
            <StatTile
              label="xG /90"
              totalVal={fmt(player.prior_xg_per_90)}
              per90Val="—"
              showPer90={false}
            />
            <StatTile
              label="xA /90"
              totalVal={fmt(player.prior_xa_per_90)}
              per90Val="—"
              showPer90={false}
            />
            <StatTile
              label="Shots /90"
              totalVal={fmt(player.prior_shots_per_90)}
              per90Val="—"
              showPer90={false}
            />
            <StatTile
              label="Key passes /90"
              totalVal={fmt(player.prior_key_passes_per_90)}
              per90Val="—"
              showPer90={false}
            />
          </motion.div>
        </div>
      )}
    </div>
  )
}
