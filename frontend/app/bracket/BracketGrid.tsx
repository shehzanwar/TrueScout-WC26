"use client"

import { motion } from "framer-motion"
import type { BracketData } from "@/lib/bracket"
import { getFlag } from "@/lib/flags"
import BracketSlot from "./BracketSlot"

// ---------------------------------------------------------------------------
// Bracket geometry constants
//
// Total height = 16 R32 slots × 80px = 1280px.
// Each round column uses flex proportions so slot heights double each round:
//   R32 = flex:1  → 80px/slot
//   R16 = flex:2  → 160px/slot
//   QF  = flex:4  → 320px/slot
//   SF  = flex:8  → 640px/slot
//   F   = flex:16 → 1280px/slot
//
// Connector groups span 2 slots of the preceding round:
//   flexPerGroup = flexOf(precedingRound) × 2
//
// Arms sit at 25% / 75% of each connector group, which always aligns with
// the vertical center of the slots feeding into that group.
// ---------------------------------------------------------------------------

const TOTAL_HEIGHT = 1280
const SLOT_FLEX: Record<string, number> = {
  R32: 1, R16: 2, QF: 4, SF: 8, F: 16,
}
const COLUMN_WIDTH = 156   // px
const CONNECTOR_WIDTH = 32 // px

// ---------------------------------------------------------------------------
// Connector column — draws the classic "]─" bracket arm between two rounds
// ---------------------------------------------------------------------------

function Connector({ count, flexPerGroup }: { count: number; flexPerGroup: number }) {
  return (
    <div className="flex flex-col h-full shrink-0" style={{ width: CONNECTOR_WIDTH }}>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="relative" style={{ flex: flexPerGroup }}>
          {/* Top horizontal arm → to vertical */}
          <div
            className="absolute h-0 border-t border-slate-700/50"
            style={{ top: "25%", left: 0, right: "20%" }}
          />
          {/* Bottom horizontal arm → to vertical */}
          <div
            className="absolute h-0 border-t border-slate-700/50"
            style={{ top: "75%", left: 0, right: "20%" }}
          />
          {/* Vertical line from 25% to 75%, at 80% from left */}
          <div
            className="absolute border-r border-slate-700/50"
            style={{ top: "25%", bottom: "25%", left: "80%", width: 0 }}
          />
          {/* Output arm → from vertical to right edge, at 50% (midpoint) */}
          <div
            className="absolute h-0 border-t border-slate-700/50"
            style={{ top: "50%", left: "80%", right: 0 }}
          />
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Champion card — right-most column
// ---------------------------------------------------------------------------

function ChampionCard({
  name,
  titleProb,
}: {
  name: string
  titleProb: number
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 h-full w-40 shrink-0">
      <div className="text-xs font-semibold uppercase tracking-widest text-emerald-500/80">
        Champion
      </div>
      <motion.div
        className="flex flex-col items-center gap-2 bg-slate-900 border border-emerald-500/25 rounded-xl px-5 py-4"
        initial={{ opacity: 0, scale: 0.92 }}
        whileInView={{ opacity: 1, scale: 1 }}
        viewport={{ once: true }}
        transition={{ duration: 0.4, ease: "easeOut" as const }}
      >
        <span className="text-3xl">{getFlag(name)}</span>
        <span className="text-sm font-bold text-slate-100 text-center leading-tight">
          {name}
        </span>
        <span className="text-xs font-medium text-emerald-400 tabular-nums">
          {(titleProb * 100).toFixed(1)}% title
        </span>
      </motion.div>
      <p className="text-[10px] text-slate-700 text-center">projected</p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Round column header row
// ---------------------------------------------------------------------------

function HeaderRow({ rounds }: { rounds: BracketData["rounds"] }) {
  const hasFive = rounds.length === 5  // R32→F
  return (
    <div className="flex items-center shrink-0 mb-2" style={{ minWidth: "max-content" }}>
      {rounds.map((round, ri) => (
        <div key={round.code} className="flex items-center">
          {ri > 0 && <div style={{ width: CONNECTOR_WIDTH }} />}
          <div
            className="text-center text-[11px] font-semibold uppercase tracking-wider text-slate-500"
            style={{ width: COLUMN_WIDTH }}
          >
            {round.label}
          </div>
        </div>
      ))}
      {/* Champion header */}
      {hasFive && (
        <div className="flex items-center">
          <div style={{ width: CONNECTOR_WIDTH }} />
          <div
            className="text-center text-[11px] font-semibold uppercase tracking-wider text-emerald-600"
            style={{ width: 160 }}
          >
            Winner
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Legend
// ---------------------------------------------------------------------------

function Legend() {
  return (
    <div className="flex items-center gap-4 text-[11px] text-slate-500 mb-4">
      <div className="flex items-center gap-1.5">
        <div className="w-8 h-3 bg-slate-900 border border-slate-700/80 rounded" />
        Confirmed fixture
      </div>
      <div className="flex items-center gap-1.5">
        <div className="w-8 h-3 bg-slate-900 border border-slate-800/60 border-dashed rounded" />
        Monte Carlo projection
      </div>
      <div className="flex items-center gap-1.5">
        <div className="flex gap-0.5">
          <div className="w-4 h-2 bg-emerald-500 rounded-sm" />
          <div className="w-3 h-2 bg-amber-500 rounded-sm" />
          <div className="w-2 h-2 bg-slate-500 rounded-sm" />
        </div>
        Advance prob (high / mid / low)
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// BracketGrid — main export
// ---------------------------------------------------------------------------

export default function BracketGrid({ bracket }: { bracket: BracketData }) {
  return (
    <div>
      <Legend />
      <HeaderRow rounds={bracket.rounds} />

      {/* Horizontally scrolling bracket */}
      <div
        className="overflow-x-auto pb-3"
        style={{ WebkitOverflowScrolling: "touch", msOverflowStyle: "none", scrollbarWidth: "none" }}
      >
        <div
          className="flex items-stretch"
          style={{ height: TOTAL_HEIGHT, minWidth: "max-content" }}
        >
          {bracket.rounds.map((round, ri) => {
            const slotFlex = SLOT_FLEX[round.code] ?? 1
            const connGroupFlex = slotFlex * 2  // each connector group spans 2 prev slots

            return (
              <div key={round.code} className="flex items-stretch">
                {/* Connector before every round except R32 */}
                {ri > 0 && (
                  <Connector
                    count={round.slots.length}
                    flexPerGroup={connGroupFlex}
                  />
                )}

                {/* Round column */}
                <div
                  className="flex flex-col h-full shrink-0"
                  style={{ width: COLUMN_WIDTH }}
                >
                  {round.slots.map((slot, si) => (
                    <div
                      key={si}
                      className="flex items-center justify-center px-1"
                      style={{ flex: slotFlex }}
                    >
                      <BracketSlot slot={slot} animDelay={si * 0.03} />
                    </div>
                  ))}
                </div>
              </div>
            )
          })}

          {/* Champion connector + card */}
          {bracket.champion && (
            <>
              {/* Champion connector: single arm at midpoint pointing right */}
              <div
                className="flex flex-col items-stretch h-full shrink-0"
                style={{ width: CONNECTOR_WIDTH }}
              >
                <div className="flex-1 relative">
                  <div
                    className="absolute h-0 border-t border-slate-700/50"
                    style={{ top: "50%", left: 0, right: 0 }}
                  />
                </div>
              </div>

              <ChampionCard
                name={bracket.champion.name}
                titleProb={bracket.champion.titleProb}
              />
            </>
          )}
        </div>
      </div>
    </div>
  )
}
