"use client"

import { motion, AnimatePresence } from "framer-motion"
import { useState } from "react"
import type { BracketTeam, BracketSlot as BracketSlotType } from "@/lib/bracket"
import { FlagIcon } from "@/app/components/FlagIcon"

// ---------------------------------------------------------------------------
// Colour helpers
// ---------------------------------------------------------------------------

function barColor(p: number): string {
  if (p >= 0.6) return "bg-emerald-500"
  if (p >= 0.35) return "bg-amber-500"
  return "bg-slate-500"
}

function nameColor(team: BracketTeam): string {
  return team.isProjected ? "text-slate-500 italic" : "text-slate-200"
}

// ---------------------------------------------------------------------------
// TeamRow — one team within the slot
// slotProb (joint match-win probability) drives the bar when available;
// advanceProb (marginal) is the fallback.
// When isWinner=true the row shows a green "Advanced" badge instead of the bar.
// ---------------------------------------------------------------------------

function TeamRow({
  team,
  delay,
  isWinner = false,
  isLoser = false,
}: {
  team: BracketTeam
  delay: number
  isWinner?: boolean
  isLoser?: boolean
}) {
  const displayProb = team.slotProb ?? team.advanceProb
  const pct         = Math.round(displayProb * 100)

  if (isWinner) {
    return (
      <div className="px-2.5 pt-1.5 pb-1 border-l-2 border-emerald-500/60">
        <div className="flex items-center gap-1.5">
          <span className="leading-none w-5 shrink-0 flex items-center justify-center">
            <FlagIcon name={team.name} size={18} />
          </span>
          <span className="flex-1 text-[11px] font-semibold leading-tight truncate text-slate-100">
            {team.name}
          </span>
          <span className="text-[9px] font-medium text-emerald-400 uppercase tracking-wide shrink-0">
            ✓ Advanced
          </span>
        </div>
      </div>
    )
  }

  if (isLoser) {
    return (
      <div className="px-2.5 pt-1.5 pb-1 opacity-40">
        <div className="flex items-center gap-1.5">
          <span className="leading-none w-5 shrink-0 flex items-center justify-center">
            <FlagIcon name={team.name} size={18} />
          </span>
          <span className="flex-1 text-[11px] font-medium leading-tight truncate text-slate-500">
            {team.name}
          </span>
        </div>
      </div>
    )
  }

  return (
    <div className={`px-2.5 pt-1.5 pb-1 ${team.isProjected ? "opacity-60" : ""}`}>
      {/* Name row */}
      <div className="flex items-center gap-1.5 mb-1">
        <span className="leading-none w-5 shrink-0 flex items-center justify-center">
          <FlagIcon name={team.name} size={18} />
        </span>
        <span className={`flex-1 text-[11px] font-medium leading-tight truncate ${nameColor(team)}`}>
          {team.name}
        </span>
        <span className="text-[10px] tabular-nums text-slate-400 shrink-0">
          {pct}%
        </span>
        <span className="text-[10px] tabular-nums text-slate-600 shrink-0 ml-0.5">
          🏆{(team.titleProb * 100).toFixed(1)}%
        </span>
      </div>

      {/* Prob bar — width driven by joint slot probability */}
      <div className="h-[3px] bg-slate-800 rounded-full overflow-hidden">
        <motion.div
          className={`h-full rounded-full ${barColor(displayProb)}`}
          initial={{ width: 0 }}
          whileInView={{ width: `${pct}%` }}
          viewport={{ once: true, margin: "0px 0px -40px 0px" }}
          transition={{ duration: 0.45, delay, ease: "easeOut" as const }}
        />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// BracketSlot — two-team match card
// ---------------------------------------------------------------------------

export default function BracketSlot({
  slot,
  animDelay = 0,
}: {
  slot: BracketSlotType
  animDelay?: number
}) {
  const [showAlts, setShowAlts] = useState(false)
  const isAllProjected = slot.top.isProjected && slot.bottom.isProjected
  const hasAlts        = slot.alts.length > 0
  const done           = slot.isCompleted ?? false

  return (
    <div
      className={[
        "w-full bg-slate-900 rounded-lg overflow-hidden",
        done
          ? "border border-emerald-900/40"
          : isAllProjected
            ? "border border-slate-800/60 border-dashed"
            : "border border-slate-700/80",
      ].join(" ")}
    >
      {/* Score chip for completed matches */}
      {done && slot.score && (
        <div className="px-2.5 pt-1 pb-0 flex items-center gap-1">
          <span className="text-[9px] text-emerald-600 uppercase tracking-widest">FT</span>
          <span className="text-[10px] font-bold tabular-nums text-slate-300">{slot.score}</span>
        </div>
      )}

      {/* Top team */}
      <div className="border-b border-slate-800/60">
        <TeamRow team={slot.top} delay={animDelay} isWinner={done} />
      </div>

      {/* Bottom team */}
      <TeamRow team={slot.bottom} delay={animDelay + 0.05} isLoser={done} />

      {/* Alt-team expansion — dark horses who occasionally win this slot */}
      {hasAlts && (
        <>
          <button
            onClick={() => setShowAlts(v => !v)}
            className="w-full px-2.5 py-0.5 text-[9px] text-slate-600 hover:text-slate-400 transition-colors text-left border-t border-slate-800/40"
          >
            {showAlts ? "▲ hide alts" : `▼ +${slot.alts.length} alt${slot.alts.length > 1 ? "s" : ""}`}
          </button>

          <AnimatePresence>
            {showAlts && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="overflow-hidden border-t border-slate-800/40"
              >
                {slot.alts.map(alt => (
                  <div key={alt.team} className="flex items-center gap-1.5 px-2.5 py-1">
                    <span className="leading-none w-5 shrink-0 flex items-center justify-center">
                      <FlagIcon name={alt.team} size={18} />
                    </span>
                    <span className="flex-1 text-[10px] text-slate-600 italic truncate">
                      {alt.team}
                    </span>
                    <span className="text-[10px] tabular-nums text-slate-700 shrink-0">
                      {Math.round(alt.prob * 100)}%
                    </span>
                  </div>
                ))}
              </motion.div>
            )}
          </AnimatePresence>
        </>
      )}
    </div>
  )
}
