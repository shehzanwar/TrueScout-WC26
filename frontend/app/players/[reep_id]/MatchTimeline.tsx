"use client"

import { motion } from "framer-motion"
import type { PlayerResponse, MatchLogEntry } from "@/lib/api"
import { FlagIcon } from "@/app/components/FlagIcon"

// ---------------------------------------------------------------------------
// Colour helpers
// ---------------------------------------------------------------------------

function ratingBorder(r: number): string {
  if (r >= 7.0) return "border-emerald-500/40 bg-emerald-500/5"
  if (r >= 6.0) return "border-amber-500/40 bg-amber-500/5"
  return "border-slate-700 bg-slate-800/40"
}

function ratingText(r: number): string {
  if (r >= 7.0) return "text-emerald-400"
  if (r >= 6.0) return "text-amber-400"
  return "text-rose-400"
}

// ---------------------------------------------------------------------------
// Single match chip
// ---------------------------------------------------------------------------

function MatchChip({ entry, i }: { entry: MatchLogEntry; i: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, delay: i * 0.05, ease: "easeOut" }}
      className={`shrink-0 w-[132px] rounded-xl border px-3 py-2.5 space-y-1.5 ${ratingBorder(entry.rating)}`}
    >
      {/* Opponent + rating */}
      <div className="flex items-center justify-between">
        <FlagIcon name={entry.opponent} size={18} />
        <span className={`text-sm font-bold tabular-nums ${ratingText(entry.rating)}`}>
          {entry.rating.toFixed(1)}
        </span>
      </div>

      {/* Score + opponent name */}
      <p className="text-[10px] text-slate-500 truncate">
        {entry.opponent} · <span className="text-slate-400 font-medium">{entry.score}</span>
      </p>

      {/* Minutes + events */}
      <div className="flex items-center gap-1.5 text-[10px]">
        <span className="text-slate-600">{entry.minutes}&apos;</span>
        {entry.goals > 0 && (
          <span className="text-emerald-500">⚽{entry.goals > 1 ? `×${entry.goals}` : ""}</span>
        )}
        {entry.assists > 0 && (
          <span className="text-sky-400">🅰{entry.assists > 1 ? `×${entry.assists}` : ""}</span>
        )}
        {entry.yellow_card && <span className="text-yellow-400 font-bold">Y</span>}
      </div>
    </motion.div>
  )
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

export default function MatchTimeline({ player }: { player: PlayerResponse }) {
  const log = player.match_log

  // No WC time at all → don't render
  if ((player.wc_minutes ?? 0) === 0) return null

  // match_log not yet in players.json (pre-PR3)
  if (!log || log.length === 0) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <h2 className="text-sm font-semibold text-slate-100 uppercase tracking-wider mb-1">
          Match by Match
        </h2>
        <p className="text-xs text-slate-600">
          Match-by-match breakdown coming in the next data update.
        </p>
      </div>
    )
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
      <div className="mb-4">
        <h2 className="text-sm font-semibold text-slate-100 uppercase tracking-wider">
          Match by Match
        </h2>
        <p className="text-xs text-slate-500 mt-0.5">
          Sofascore rating · colour: green ≥7.0 / amber 6.0–7.0 / red &lt;6.0
        </p>
      </div>

      <div className="flex gap-3 overflow-x-auto pb-1 -mx-1 px-1 scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent">
        {log.map((entry, i) => (
          <MatchChip key={i} entry={entry} i={i} />
        ))}
      </div>
    </div>
  )
}
