"use client"

import { useState, useEffect, useCallback, useRef } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import Link from "next/link"
import type { PlayerResponse } from "@/lib/api"
import { normalizeString } from "@/lib/api"
import { FlagIcon } from "@/app/components/FlagIcon"

function confBadge(score: number) {
  if (score >= 0.7) return { label: "High",     cls: "text-emerald-400" }
  if (score >= 0.4) return { label: "Moderate", cls: "text-amber-400" }
  return               { label: "Sparse",   cls: "text-rose-400" }
}

// ---------------------------------------------------------------------------
// PlayerSearchBox — mini inline search
// ---------------------------------------------------------------------------

function PlayerSearchBox({
  label,
  all,
  onSelect,
  selected,
}: {
  label: string
  all: PlayerResponse[]
  onSelect: (p: PlayerResponse) => void
  selected: PlayerResponse | null
}) {
  const [q, setQ]           = useState("")
  const [open, setOpen]     = useState(false)
  const boxRef              = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (selected) setQ("")
  }, [selected])

  // Close on outside click
  useEffect(() => {
    function handle(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener("mousedown", handle)
    return () => document.removeEventListener("mousedown", handle)
  }, [])

  const results = q.trim().length >= 2
    ? all
        .filter((p) => normalizeString(p.name ?? "").includes(normalizeString(q)))
        .sort((a, b) => b.confidence_score - a.confidence_score || b.posterior_mean - a.posterior_mean)
        .slice(0, 8)
    : []

  return (
    <div ref={boxRef} className="relative">
      <p className="text-[10px] uppercase tracking-wider text-slate-600 mb-1">{label}</p>
      <input
        value={q}
        onChange={(e) => { setQ(e.target.value); setOpen(true) }}
        onFocus={() => setOpen(true)}
        placeholder={selected ? (selected.name ?? selected.reep_id) : "Search player…"}
        className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none focus:border-emerald-500/50"
      />
      {open && results.length > 0 && (
        <div className="absolute z-40 top-full mt-1 left-0 right-0 bg-slate-900 border border-slate-700 rounded-lg shadow-xl overflow-hidden">
          {results.map((p) => (
            <button
              key={p.reep_id}
              onMouseDown={(e) => { e.preventDefault(); onSelect(p); setOpen(false); setQ("") }}
              className="w-full flex items-center gap-2 px-3 py-2 hover:bg-slate-800 text-left transition-colors"
            >
              <span className="shrink-0"><FlagIcon name={p.nationality} size={16} /></span>
              <div className="flex-1 min-w-0">
                <p className="text-sm text-slate-100 truncate">{p.name ?? p.reep_id}</p>
                <p className="text-xs text-slate-500 truncate">
                  {p.nationality} · {p.position_micro ?? p.position_macro}
                </p>
              </div>
              <span className="text-xs font-mono text-emerald-400 shrink-0">
                {p.posterior_mean.toFixed(2)}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// MetricBar — one comparison metric row
// ---------------------------------------------------------------------------

function MetricBar({
  label,
  valA,
  valB,
  fmt = (v: number) => v.toFixed(2),
  invert = false,   // lower is better
}: {
  label: string
  valA: number | null | undefined
  valB: number | null | undefined
  fmt?: (v: number) => string
  invert?: boolean
}) {
  const a = valA ?? 0
  const b = valB ?? 0
  const max = Math.max(a, b, 0.001)

  const aWins = invert ? a < b : a > b
  const bWins = invert ? b < a : b > a

  const aColor = valA == null ? "bg-slate-700" : aWins ? "bg-emerald-500" : bWins ? "bg-slate-600" : "bg-slate-600"
  const bColor = valB == null ? "bg-slate-700" : bWins ? "bg-emerald-500" : aWins ? "bg-slate-600" : "bg-slate-600"
  const aText  = aWins ? "text-emerald-400" : "text-slate-400"
  const bText  = bWins ? "text-emerald-400" : "text-slate-400"

  return (
    <div className="space-y-0.5">
      <p className="text-[10px] uppercase tracking-wider text-slate-600 text-center">{label}</p>
      <div className="flex items-center gap-2">
        {/* Left bar (reversed direction — grows left) */}
        <div className="flex-1 flex justify-end">
          <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden flex justify-end">
            <div
              className={`h-full ${aColor} rounded-full transition-[width] duration-500`}
              style={{ width: `${(a / max) * 100}%` }}
            />
          </div>
        </div>
        {/* Values */}
        <div className="flex items-center gap-1 shrink-0 w-28 justify-center">
          <span className={`text-xs font-mono tabular-nums ${aText}`}>
            {valA != null ? fmt(valA) : "—"}
          </span>
          <span className="text-slate-700 text-[10px]">vs</span>
          <span className={`text-xs font-mono tabular-nums ${bText}`}>
            {valB != null ? fmt(valB) : "—"}
          </span>
        </div>
        {/* Right bar */}
        <div className="flex-1">
          <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
            <div
              className={`h-full ${bColor} rounded-full transition-[width] duration-500`}
              style={{ width: `${(b / max) * 100}%` }}
            />
          </div>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// PlayerCard — compact side-by-side profile
// ---------------------------------------------------------------------------

function PlayerCard({ player, side }: { player: PlayerResponse; side: "left" | "right" }) {
  const conf  = confBadge(player.confidence_score)
  const align = side === "left" ? "items-start text-left" : "items-end text-right"

  return (
    <div className={`flex flex-col gap-1 ${align}`}>
      <FlagIcon name={player.nationality} size={36} />
      <Link
        href={`/players/${player.reep_id}`}
        className="text-base font-bold text-slate-100 hover:text-emerald-400 transition-colors leading-tight"
      >
        {player.name ?? player.reep_id}
      </Link>
      <p className="text-xs text-slate-500">
        {player.nationality} · {player.position_detail ?? player.position_micro ?? player.position_macro}
      </p>
      <p className="text-2xl font-bold text-emerald-400 tabular-nums mt-1">
        {player.posterior_mean.toFixed(2)}
        <span className="text-sm text-slate-500 font-normal">/10</span>
      </p>
      {player.fifa?.overall != null && (
        <p className="text-xs text-slate-600">
          FIFA {player.fifa.overall} · {player.fifa.band}
        </p>
      )}
      <span className={`text-[11px] font-medium ${conf.cls}`}>{conf.label} confidence</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

export default function CompareClient({ allPlayers }: { allPlayers: PlayerResponse[] }) {
  const router       = useRouter()
  const searchParams = useSearchParams()

  const [playerA, setPlayerA] = useState<PlayerResponse | null>(null)
  const [playerB, setPlayerB] = useState<PlayerResponse | null>(null)

  // Resolve URL params → players on mount and when URL changes
  useEffect(() => {
    const idA = searchParams.get("a")
    const idB = searchParams.get("b")
    if (idA) setPlayerA(allPlayers.find((p) => p.reep_id === idA) ?? null)
    if (idB) setPlayerB(allPlayers.find((p) => p.reep_id === idB) ?? null)
  }, [searchParams, allPlayers])

  const pick = useCallback((slot: "a" | "b") => (p: PlayerResponse) => {
    const current = new URLSearchParams(searchParams.toString())
    current.set(slot, p.reep_id)
    router.replace(`/compare?${current.toString()}`, { scroll: false })
    if (slot === "a") setPlayerA(p)
    else setPlayerB(p)
  }, [router, searchParams])

  const bothSelected = playerA !== null && playerB !== null

  return (
    <div className="space-y-6">
      {/* Search row */}
      <div className="grid grid-cols-2 gap-4">
        <PlayerSearchBox label="Player A" all={allPlayers} selected={playerA} onSelect={pick("a")} />
        <PlayerSearchBox label="Player B" all={allPlayers} selected={playerB} onSelect={pick("b")} />
      </div>

      {/* Empty state */}
      {!bothSelected && (
        <div className="py-16 flex flex-col items-center gap-2 text-center text-slate-600 border border-dashed border-slate-800 rounded-xl">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className="w-8 h-8">
            <path strokeLinecap="round" strokeLinejoin="round"
              d="M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 0A17.933 17.933 0 0 1 12 21.75c-2.676 0-5.216-.584-7.499-1.632Z" />
          </svg>
          <p className="text-sm">Search for two players above to compare them</p>
        </div>
      )}

      {/* Comparison */}
      {bothSelected && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-6">
          {/* Header: player cards */}
          <div className="grid grid-cols-2 gap-4">
            <PlayerCard player={playerA} side="left" />
            <PlayerCard player={playerB} side="right" />
          </div>

          {/* Divider */}
          <div className="border-t border-slate-800" />

          {/* Metric comparisons */}
          <div className="space-y-4">
            <p className="text-xs uppercase tracking-wider text-slate-600">Head-to-head</p>

            <MetricBar
              label="Overall Rating"
              valA={playerA.posterior_mean}
              valB={playerB.posterior_mean}
            />
            <MetricBar
              label="Rating range (high)"
              valA={playerA.hdi_high}
              valB={playerB.hdi_high}
            />
            <MetricBar
              label="Shooting"
              valA={playerA.radar?.shooting}
              valB={playerB.radar?.shooting}
              fmt={(v) => `${Math.round(v * 100)}%`}
            />
            <MetricBar
              label="Creativity"
              valA={playerA.radar?.creativity}
              valB={playerB.radar?.creativity}
              fmt={(v) => `${Math.round(v * 100)}%`}
            />
            <MetricBar
              label="Defending"
              valA={playerA.radar?.defending}
              valB={playerB.radar?.defending}
              fmt={(v) => `${Math.round(v * 100)}%`}
            />
            <MetricBar
              label="WC Form"
              valA={playerA.radar?.wc_form}
              valB={playerB.radar?.wc_form}
              fmt={(v) => `${Math.round(v * 100)}%`}
            />
            <MetricBar
              label="WC Minutes"
              valA={playerA.wc_minutes}
              valB={playerB.wc_minutes}
              fmt={(v) => `${Math.round(v)}'`}
            />
            <MetricBar
              label="Club form weight"
              valA={playerA.shrinkage_weight}
              valB={playerB.shrinkage_weight}
              fmt={(v) => `${Math.round(v * 100)}%`}
            />
          </div>

          {/* Verdict */}
          <div className="border-t border-slate-800 pt-4">
            {(() => {
              const delta = playerA.posterior_mean - playerB.posterior_mean
              const absDelta = Math.abs(delta)
              const winner = delta > 0 ? playerA : delta < 0 ? playerB : null
              if (!winner) {
                return (
                  <p className="text-sm text-slate-400 text-center">
                    These players are essentially equal in rating.
                  </p>
                )
              }
              const loser = winner === playerA ? playerB : playerA
              const verdict =
                absDelta >= 1.5
                  ? `${winner.name} is significantly stronger — a ${absDelta.toFixed(2)}-point gap is meaningful.`
                  : absDelta >= 0.5
                  ? `${winner.name} edges ${loser.name} by ${absDelta.toFixed(2)} points — a real but narrow advantage.`
                  : `${winner.name} has a marginal edge (${absDelta.toFixed(2)} pts) — both players are broadly comparable.`
              return (
                <p className="text-sm text-slate-400 text-center leading-relaxed">{verdict}</p>
              )
            })()}
          </div>
        </div>
      )}
    </div>
  )
}
