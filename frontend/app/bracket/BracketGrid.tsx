"use client"

import { useState } from "react"
import { motion } from "framer-motion"
import type { BracketData } from "@/lib/bracket"
import type { MatchupsResponse, Matchup } from "@/lib/api"
import { FlagIcon } from "@/app/components/FlagIcon"
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
  const confirmed = titleProb >= 1.0
  return (
    <div className="flex flex-col items-center justify-center gap-3 h-full w-40 shrink-0">
      <div className={`text-xs font-semibold uppercase tracking-widest ${confirmed ? "text-amber-400/80" : "text-emerald-500/80"}`}>
        {confirmed ? "🏆 Champion" : "Projected"}
      </div>
      <motion.div
        className={`flex flex-col items-center gap-2 rounded-xl px-5 py-4 ${
          confirmed
            ? "bg-amber-950/60 border border-amber-500/40 ring-1 ring-amber-500/15"
            : "bg-slate-900 border border-emerald-500/25"
        }`}
        initial={{ opacity: 0, scale: 0.92 }}
        whileInView={{ opacity: 1, scale: 1 }}
        viewport={{ once: true }}
        transition={{ duration: 0.4, ease: "easeOut" as const }}
      >
        <FlagIcon name={name} size={36} />
        <span className="text-sm font-bold text-slate-100 text-center leading-tight">
          {name}
        </span>
        {confirmed ? (
          <span className="text-[10px] font-bold text-amber-400 uppercase tracking-wide">WC 2026</span>
        ) : (
          <span className="text-xs font-medium text-emerald-400 tabular-nums">
            {(titleProb * 100).toFixed(1)}% title
          </span>
        )}
      </motion.div>
      {!confirmed && <p className="text-[10px] text-slate-700 text-center">projected</p>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Champion callout — below the Final column once confirmed
// ---------------------------------------------------------------------------

function ChampionCallout({ name }: { name: string }) {
  return (
    <div style={{ width: COLUMN_WIDTH }}>
      <div className="flex flex-col items-center gap-1 mb-2">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-amber-500/80">🏆 WC 2026 Champions</span>
      </div>
      <div className="w-full bg-amber-950/60 border border-amber-500/35 rounded-lg overflow-hidden">
        <div className="flex items-center gap-2.5 px-3 py-2.5">
          <FlagIcon name={name} size={22} />
          <span className="text-sm font-bold text-slate-100 truncate">{name}</span>
          <span className="ml-auto text-[10px] font-bold text-amber-400 shrink-0 uppercase tracking-wide">Final</span>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Third-place slot — rendered below the Final column
// ---------------------------------------------------------------------------

function ThirdPlaceTeamRow({
  name,
  prob,
  isWinner,
  isLoser,
}: {
  name: string
  prob: number | null
  isWinner: boolean
  isLoser: boolean
}) {
  if (isWinner) {
    return (
      <div className="px-2.5 pt-1.5 pb-1 border-l-2 border-amber-600/60">
        <div className="flex items-center gap-1.5">
          <span className="leading-none w-5 shrink-0 flex items-center justify-center">
            <FlagIcon name={name} size={18} />
          </span>
          <span className="flex-1 text-[11px] font-semibold leading-tight truncate text-slate-100">
            {name}
          </span>
          <span className="text-[9px] font-medium text-amber-500 uppercase tracking-wide shrink-0">
            3rd
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
            <FlagIcon name={name} size={18} />
          </span>
          <span className="flex-1 text-[11px] font-medium leading-tight truncate text-slate-500">
            {name}
          </span>
        </div>
      </div>
    )
  }

  const pct = prob !== null ? Math.round(prob * 100) : null
  return (
    <div className="px-2.5 pt-1.5 pb-1">
      <div className="flex items-center gap-1.5 mb-1">
        <span className="leading-none w-5 shrink-0 flex items-center justify-center">
          <FlagIcon name={name} size={18} />
        </span>
        <span className="flex-1 text-[11px] font-medium leading-tight truncate text-slate-200">
          {name}
        </span>
        {pct !== null && (
          <span className="text-[10px] tabular-nums text-slate-400 shrink-0">{pct}%</span>
        )}
      </div>
      {pct !== null && (
        <div className="h-[3px] bg-slate-800 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full ${pct >= 60 ? "bg-emerald-500" : pct >= 35 ? "bg-amber-500" : "bg-slate-500"}`}
            style={{ width: `${pct}%` }}
          />
        </div>
      )}
    </div>
  )
}

function ThirdPlaceSlot({ match }: { match: Matchup }) {
  const { home, away, is_completed } = match

  const winner =
    match.winner ??
    (home.score !== null && away.score !== null
      ? home.score > away.score
        ? home.name
        : away.score > home.score
          ? away.name
          : null
      : null)

  let score: string | undefined
  if (is_completed && home.score !== null && away.score !== null && winner) {
    const ws = winner === home.name ? home.score : away.score
    const ls = winner === home.name ? away.score : home.score
    score = `${ws}–${ls}`
  }

  return (
    <div style={{ width: COLUMN_WIDTH }}>
      {/* Label — matches HeaderRow column header style */}
      <div className="flex flex-col items-center gap-1 mb-2">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-amber-600/80">
          3rd Place
        </span>
      </div>

      <div
        className={[
          "w-full bg-slate-900 rounded-lg overflow-hidden",
          is_completed
            ? "border border-amber-900/50"
            : "border border-amber-800/30 border-dashed",
        ].join(" ")}
      >
        {is_completed && score && (
          <div className="px-2.5 pt-1 pb-0 flex items-center gap-1">
            <span className="text-[9px] text-amber-700/80 uppercase tracking-widest">FT</span>
            <span className="text-[10px] font-bold tabular-nums text-slate-300">{score}</span>
          </div>
        )}

        <div className="border-b border-slate-800/60">
          <ThirdPlaceTeamRow
            name={home.name}
            prob={home.model_advance_prob}
            isWinner={winner === home.name}
            isLoser={is_completed && winner !== home.name}
          />
        </div>

        <ThirdPlaceTeamRow
          name={away.name}
          prob={away.model_advance_prob}
          isWinner={winner === away.name}
          isLoser={is_completed && winner !== away.name}
        />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Chaos meter helpers
// ---------------------------------------------------------------------------

function chaosColor(score: number): string {
  if (score >= 0.65) return "bg-rose-500"
  if (score >= 0.4)  return "bg-amber-500"
  return "bg-emerald-600"
}

function chaosBadge(score: number): string {
  if (score >= 0.65) return "text-rose-400"
  if (score >= 0.4)  return "text-amber-400"
  return "text-emerald-500"
}

// ---------------------------------------------------------------------------
// Round column header row
// ---------------------------------------------------------------------------

function HeaderRow({ rounds }: { rounds: BracketData["rounds"] }) {
  const hasFive = rounds.length === 5  // R32→F
  return (
    <div className="flex items-start shrink-0 mb-2" style={{ minWidth: "max-content" }}>
      {rounds.map((round, ri) => (
        <div key={round.code} className="flex items-start">
          {ri > 0 && <div style={{ width: CONNECTOR_WIDTH }} />}
          <div
            className="flex flex-col items-center gap-1"
            style={{ width: COLUMN_WIDTH }}
          >
            <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
              {round.label}
            </span>
            {/* Chaos meter — how evenly matched is this round? */}
            <div className="flex flex-col items-center gap-0.5">
              <div
                className="flex items-center gap-1 cursor-help"
                title="Chaos score: match competitiveness. 100% = every match is a perfect coin flip. 60% = typical 70/30 favourite. Low scores mean the round is dominated by clear favourites."
              >
                <span className="text-[8px] uppercase tracking-widest text-slate-600">chaos</span>
                <span className="text-[8px] text-slate-700 border border-slate-700 rounded-full w-3 h-3 flex items-center justify-center leading-none">?</span>
              </div>
              <div className="flex items-center gap-1">
                <div className="w-12 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${chaosColor(round.chaosScore)}`}
                    style={{ width: `${round.chaosScore * 100}%` }}
                  />
                </div>
                <span className={`text-[9px] tabular-nums ${chaosBadge(round.chaosScore)}`}>
                  {(round.chaosScore * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          </div>
        </div>
      ))}
      {/* Champion header */}
      {hasFive && (
        <div className="flex items-start">
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

function ShareButton() {
  const [copied, setCopied] = useState(false)

  async function handleShare() {
    try {
      await navigator.clipboard.writeText(window.location.href)
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    } catch {
      // Clipboard API unavailable — silently ignore
    }
  }

  return (
    <button
      onClick={handleShare}
      className="flex items-center gap-1.5 text-[11px] text-slate-500 hover:text-slate-300 border border-slate-800 hover:border-slate-700 rounded-full px-3 py-1.5 transition-colors shrink-0"
    >
      {copied ? (
        <>
          <svg viewBox="0 0 16 16" fill="currentColor" className="w-3.5 h-3.5 text-emerald-400">
            <path fillRule="evenodd" d="M13.78 4.22a.75.75 0 0 1 0 1.06l-7.25 7.25a.75.75 0 0 1-1.06 0L2.22 9.28a.75.75 0 0 1 1.06-1.06L6 10.94l6.72-6.72a.75.75 0 0 1 1.06 0Z" clipRule="evenodd" />
          </svg>
          <span className="text-emerald-400">Link copied</span>
        </>
      ) : (
        <>
          <svg viewBox="0 0 16 16" fill="currentColor" className="w-3.5 h-3.5">
            <path d="M11 2a2.5 2.5 0 1 0-2.466 2.5l-3.07 3.07a2.5 2.5 0 1 0 0 .86l3.07 3.07a2.5 2.5 0 1 0 .53-.53l-3.07-3.07a2.5 2.5 0 0 0 0-.86l3.07-3.07c.286.18.62.3.98.34A2.5 2.5 0 0 0 11 2Z" />
          </svg>
          Share bracket
        </>
      )}
    </button>
  )
}

function Legend() {
  return (
    <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
      <div className="flex flex-wrap items-center gap-4 text-[11px] text-slate-500">
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
          Match-win prob (high / mid / low)
        </div>
        <div className="flex items-center gap-1.5">
          <div className="flex items-center gap-0.5">
            <div className="w-6 h-1.5 bg-rose-500 rounded-full" />
            <span className="text-rose-400 text-[9px]">%</span>
          </div>
          Chaos meter (avg match entropy)
        </div>
      </div>
      <ShareButton />
    </div>
  )
}

// ---------------------------------------------------------------------------
// BracketGrid — main export
// ---------------------------------------------------------------------------

export default function BracketGrid({
  bracket,
  thirdPlace,
}: {
  bracket: BracketData
  thirdPlace?: MatchupsResponse | null
}) {
  return (
    <div>
      <Legend />

      {/* Horizontally scrolling bracket — header scrolls in sync with columns */}
      <div
        className="overflow-x-auto pb-3"
        style={{ WebkitOverflowScrolling: "touch", msOverflowStyle: "none", scrollbarWidth: "none" }}
      >
        {/* Single min-width wrapper so header + bracket scroll together */}
        <div style={{ minWidth: "max-content" }}>
          <HeaderRow rounds={bracket.rounds} />

          <div className="flex items-stretch" style={{ height: TOTAL_HEIGHT }}>
            {bracket.rounds.map((round, ri) => {
              const slotFlex = SLOT_FLEX[round.code] ?? 1
              const connGroupFlex = slotFlex * 2

              return (
                <div key={round.code} className="flex items-stretch">
                  {ri > 0 && (
                    <Connector
                      count={round.slots.length}
                      flexPerGroup={connGroupFlex}
                    />
                  )}
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

            {bracket.champion && (
              <>
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

          {/* Champion callout + 3rd-place slot — below the Final column */}
          {(bracket.champion?.titleProb ?? 0) >= 1.0 && (
            <div
              className="flex mt-4"
              style={{
                paddingLeft:
                  (bracket.rounds.length - 1) * (COLUMN_WIDTH + CONNECTOR_WIDTH),
              }}
            >
              <ChampionCallout name={bracket.champion!.name} />
            </div>
          )}
          {thirdPlace?.matches[0] && (
            <div
              className="flex mt-3"
              style={{
                paddingLeft:
                  (bracket.rounds.length - 1) * (COLUMN_WIDTH + CONNECTOR_WIDTH),
              }}
            >
              <ThirdPlaceSlot match={thirdPlace.matches[0]} />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
