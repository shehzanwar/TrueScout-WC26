"use client"

import { useState, useMemo } from "react"
import Link from "next/link"
import type { BrierEntry } from "@/lib/api"
import { FlagIcon } from "@/app/components/FlagIcon"

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const ROUND_ORDER: Record<string, number> = {
  R32: 0, R16: 1, QF: 2, SF: 3, F: 4,
}

function shortRound(r: string): string {
  if (r.includes("32")) return "R32"
  if (r.includes("16")) return "R16"
  if (/quarter/i.test(r)) return "QF"
  if (/semi/i.test(r)) return "SF"
  if (/final/i.test(r) && !/semi|quarter/i.test(r)) return "F"
  return r
}

function pct(v: number | null): string {
  return v === null ? "—" : `${(v * 100).toFixed(1)}%`
}

function fmtBrierDelta(v: number | null): { text: string; cls: string } {
  if (v === null) return { text: "—", cls: "text-slate-600" }
  const sign = v >= 0 ? "+" : ""
  const cls = v > 0.01 ? "text-emerald-400" : v < -0.01 ? "text-rose-400" : "text-slate-400"
  return { text: `${sign}${v.toFixed(4)}`, cls }
}

// ---------------------------------------------------------------------------
// Processed row
// ---------------------------------------------------------------------------

type RowType = "edge" | "upset" | "normal"

interface Row {
  entry: BrierEntry
  shortRound: string
  modelWinnerProb: number | null
  marketWinnerProb: number | null
  brierDelta: number | null   // brier_market - brier_model (positive = model did better)
  rowType: RowType
}

function processEntries(entries: BrierEntry[]): Row[] {
  return entries.map(e => {
    const homeWon = e.advanced_team === e.home_team
    const mwp = e.model_prob === null ? null : homeWon ? e.model_prob : 1 - e.model_prob
    const mkwp = e.market_prob === null ? null : homeWon ? e.market_prob : 1 - e.market_prob
    const delta = e.brier_model !== null && e.brier_market !== null
      ? e.brier_market - e.brier_model
      : null

    let rowType: RowType = "normal"
    if (mwp !== null && mkwp !== null && mwp > 0.6 && mkwp < 0.4) {
      rowType = "edge"       // model called it, market didn't
    } else if (mwp !== null && mwp < 0.3) {
      rowType = "upset"      // model was surprised
    }

    return {
      entry: e,
      shortRound: shortRound(e.round),
      modelWinnerProb: mwp,
      marketWinnerProb: mkwp,
      brierDelta: delta,
      rowType,
    }
  })
}

// ---------------------------------------------------------------------------
// Sort state
// ---------------------------------------------------------------------------

type SortKey = "round" | "modelProb" | "marketProb" | "brierDelta"
type SortDir = "asc" | "desc"

function sortRows(rows: Row[], key: SortKey, dir: SortDir): Row[] {
  return [...rows].sort((a, b) => {
    let av: number
    let bv: number
    switch (key) {
      case "round":
        av = ROUND_ORDER[a.shortRound] ?? 99
        bv = ROUND_ORDER[b.shortRound] ?? 99
        break
      case "modelProb":
        av = a.modelWinnerProb ?? -1
        bv = b.modelWinnerProb ?? -1
        break
      case "marketProb":
        av = a.marketWinnerProb ?? -1
        bv = b.marketWinnerProb ?? -1
        break
      case "brierDelta":
        av = a.brierDelta ?? -999
        bv = b.brierDelta ?? -999
        break
    }
    return dir === "asc" ? av - bv : bv - av
  })
}

// ---------------------------------------------------------------------------
// Column header with sort indicator
// ---------------------------------------------------------------------------

function Th({
  label,
  sortKey,
  current,
  dir,
  onClick,
  align = "left",
}: {
  label: string
  sortKey: SortKey
  current: SortKey
  dir: SortDir
  onClick: (k: SortKey) => void
  align?: "left" | "right"
}) {
  const active = current === sortKey
  return (
    <th
      className={`px-3 py-2.5 text-[10px] font-semibold uppercase tracking-wider cursor-pointer select-none
        hover:text-slate-300 transition-colors whitespace-nowrap
        ${active ? "text-emerald-400" : "text-slate-500"}
        ${align === "right" ? "text-right" : "text-left"}
      `}
      onClick={() => onClick(sortKey)}
    >
      {label}
      {active && (
        <span className="ml-1">{dir === "asc" ? "↑" : "↓"}</span>
      )}
    </th>
  )
}

// ---------------------------------------------------------------------------
// Row highlight classes
// ---------------------------------------------------------------------------

function rowClass(type: RowType): string {
  switch (type) {
    case "edge":
      return "bg-emerald-500/5 border-l-2 border-emerald-500/40"
    case "upset":
      return "bg-rose-500/5 border-l-2 border-rose-500/30"
    default:
      return "border-l-2 border-transparent hover:bg-slate-800/40"
  }
}

function probClass(v: number | null): string {
  if (v === null) return "text-slate-600"
  if (v >= 0.65) return "text-emerald-400"  // clear correct call
  if (v < 0.40)  return "text-rose-400"      // model/market was surprised
  return "text-slate-300"                     // marginal — no strong signal
}

// ---------------------------------------------------------------------------
// MatchLogTable — main export
// ---------------------------------------------------------------------------

export default function MatchLogTable({ entries }: { entries: BrierEntry[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("round")
  const [sortDir, setSortDir] = useState<SortDir>("asc")

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir(d => d === "asc" ? "desc" : "asc")
    } else {
      setSortKey(key)
      setSortDir(key === "brierDelta" ? "desc" : "asc")
    }
  }

  const rows = useMemo(
    () => sortRows(processEntries(entries), sortKey, sortDir),
    [entries, sortKey, sortDir]
  )

  if (rows.length === 0) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 text-center">
        <p className="text-slate-500 text-sm">No graded matches yet.</p>
      </div>
    )
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
      <div className="px-5 pt-5 pb-3 border-b border-slate-800">
        <p className="text-sm font-semibold text-slate-100 uppercase tracking-wider">
          Match Log
        </p>
        <p className="text-xs text-slate-500 mt-0.5">
          All graded knockout fixtures · probabilities locked in before kickoff · click to sort
        </p>

        {/* Legend */}
        <div className="flex flex-wrap gap-3 mt-3 text-[10px] text-slate-500">
          <span className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-sm bg-emerald-500/20 border border-emerald-500/40 inline-block" />
            Model called it, market missed
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-sm bg-rose-500/20 border border-rose-500/30 inline-block" />
            Model surprised by upset
          </span>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px]">
          <thead>
            <tr className="border-b border-slate-800 bg-slate-950/50">
              <Th label="Round"       sortKey="round"      current={sortKey} dir={sortDir} onClick={handleSort} />
              <th className="px-3 py-2.5 text-left text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                Match
              </th>
              <th className="px-3 py-2.5 text-left text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                Winner
              </th>
              <Th label="Model % *"   sortKey="modelProb"  current={sortKey} dir={sortDir} onClick={handleSort} align="right" />
              <Th label="Market %"    sortKey="marketProb" current={sortKey} dir={sortDir} onClick={handleSort} align="right" />
              <Th label="Δ Brier"     sortKey="brierDelta" current={sortKey} dir={sortDir} onClick={handleSort} align="right" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/50">
            {rows.map(row => {
              const { entry: e } = row
              const delta = fmtBrierDelta(row.brierDelta)
              return (
                <tr key={e.event_id} className={`text-sm transition-colors ${rowClass(row.rowType)}`}>
                  {/* Round — links to the matchups page for that round */}
                  <td className="px-3 py-3 text-xs font-medium whitespace-nowrap">
                    <Link
                      href={`/matchups?round=${row.shortRound}`}
                      className="text-slate-400 hover:text-slate-100 underline underline-offset-2 decoration-slate-700 hover:decoration-slate-400 transition-colors"
                    >
                      {row.shortRound}
                    </Link>
                  </td>

                  {/* Match */}
                  <td className="px-3 py-3 text-xs text-slate-400 whitespace-nowrap">
                    <FlagIcon name={e.home_team} size={13} />
                    {" "}{e.home_team}
                    <span className="mx-1.5 text-slate-700">vs</span>
                    <FlagIcon name={e.away_team} size={13} />
                    {" "}{e.away_team}
                  </td>

                  {/* Winner */}
                  <td className="px-3 py-3 text-xs font-semibold text-slate-200 whitespace-nowrap">
                    <FlagIcon name={e.advanced_team} size={13} />
                    {" "}{e.advanced_team}
                  </td>

                  {/* Model % for winner */}
                  <td className={`px-3 py-3 text-right text-sm tabular-nums ${probClass(row.modelWinnerProb)}`}>
                    {pct(row.modelWinnerProb)}
                  </td>

                  {/* Market % for winner */}
                  <td className={`px-3 py-3 text-right text-sm tabular-nums ${probClass(row.marketWinnerProb)}`}>
                    {pct(row.marketWinnerProb)}
                  </td>

                  {/* Δ Brier */}
                  <td className={`px-3 py-3 text-right text-xs font-mono tabular-nums ${delta.cls}`}>
                    {delta.text}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="px-5 py-3 border-t border-slate-800 text-[10px] text-slate-700 space-y-0.5">
        <p>Δ Brier = market_brier − model_brier · positive = model did better</p>
        <p>* Model % = pre-match probability, locked in before kickoff — differs from live simulation odds shown on the dashboard</p>
      </div>
    </div>
  )
}
