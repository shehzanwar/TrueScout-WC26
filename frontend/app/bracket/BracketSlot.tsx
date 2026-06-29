"use client"

import { motion } from "framer-motion"
import type { BracketTeam, BracketSlot as BracketSlotType } from "@/lib/bracket"
import { getFlag } from "@/lib/flags"

// ---------------------------------------------------------------------------
// Colour helpers
// ---------------------------------------------------------------------------

function barColor(p: number): string {
  if (p >= 0.7) return "bg-emerald-500"
  if (p >= 0.4) return "bg-amber-500"
  return "bg-slate-500"
}

function nameColor(team: BracketTeam): string {
  return team.isProjected ? "text-slate-500 italic" : "text-slate-200"
}

// ---------------------------------------------------------------------------
// TeamRow — one team within the slot
// ---------------------------------------------------------------------------

function TeamRow({ team, delay }: { team: BracketTeam; delay: number }) {
  const pct = Math.round(team.advanceProb * 100)
  return (
    <div className={`px-2.5 pt-1.5 pb-1 ${team.isProjected ? "opacity-60" : ""}`}>
      {/* Name row */}
      <div className="flex items-center gap-1.5 mb-1">
        <span className="text-sm leading-none w-5 text-center shrink-0">
          {getFlag(team.name)}
        </span>
        <span className={`flex-1 text-[11px] font-medium leading-tight truncate ${nameColor(team)}`}>
          {team.name}
        </span>
        <span className="text-[10px] tabular-nums text-slate-600 shrink-0">
          {(team.titleProb * 100).toFixed(1)}%
        </span>
      </div>

      {/* Prob bar */}
      <div className="h-[3px] bg-slate-800 rounded-full overflow-hidden">
        <motion.div
          className={`h-full rounded-full ${barColor(team.advanceProb)}`}
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
  const isAllProjected = slot.top.isProjected && slot.bottom.isProjected

  return (
    <div
      className={[
        "w-full bg-slate-900 rounded-lg overflow-hidden",
        isAllProjected
          ? "border border-slate-800/60 border-dashed"
          : "border border-slate-700/80",
      ].join(" ")}
    >
      {/* Top team */}
      <div className="border-b border-slate-800/60">
        <TeamRow team={slot.top} delay={animDelay} />
      </div>

      {/* Bottom team */}
      <TeamRow team={slot.bottom} delay={animDelay + 0.05} />
    </div>
  )
}
