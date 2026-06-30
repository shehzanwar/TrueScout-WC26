"use client"

import { useState, useCallback } from "react"
import { motion, AnimatePresence } from "framer-motion"
import Link from "next/link"
import type { Matchup, PlayerSearchResult, PlayerResponse } from "@/lib/api"

// ---------------------------------------------------------------------------
// Country flag lookup for WC 2026 teams
// ---------------------------------------------------------------------------

const FLAGS: Record<string, string> = {
  Argentina: "🇦🇷",
  Australia: "🇦🇺",
  Austria: "🇦🇹",
  Belgium: "🇧🇪",
  Bolivia: "🇧🇴",
  Brazil: "🇧🇷",
  Cameroon: "🇨🇲",
  Canada: "🇨🇦",
  Chile: "🇨🇱",
  Colombia: "🇨🇴",
  "Costa Rica": "🇨🇷",
  Croatia: "🇭🇷",
  Denmark: "🇩🇰",
  Ecuador: "🇪🇨",
  Egypt: "🇪🇬",
  England: "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
  France: "🇫🇷",
  Germany: "🇩🇪",
  Ghana: "🇬🇭",
  Honduras: "🇭🇳",
  Hungary: "🇭🇺",
  Indonesia: "🇮🇩",
  Iran: "🇮🇷",
  Japan: "🇯🇵",
  "Korea Republic": "🇰🇷",
  "South Korea": "🇰🇷",
  Mexico: "🇲🇽",
  Morocco: "🇲🇦",
  Netherlands: "🇳🇱",
  "New Zealand": "🇳🇿",
  Nigeria: "🇳🇬",
  Panama: "🇵🇦",
  Paraguay: "🇵🇾",
  Peru: "🇵🇪",
  Poland: "🇵🇱",
  Portugal: "🇵🇹",
  Qatar: "🇶🇦",
  Romania: "🇷🇴",
  "Saudi Arabia": "🇸🇦",
  Scotland: "🏴󠁧󠁢󠁳󠁣󠁴󠁿",
  Senegal: "🇸🇳",
  Serbia: "🇷🇸",
  Slovenia: "🇸🇮",
  Spain: "🇪🇸",
  Switzerland: "🇨🇭",
  Tunisia: "🇹🇳",
  Turkey: "🇹🇷",
  Türkiye: "🇹🇷",
  Ukraine: "🇺🇦",
  "United States": "🇺🇸",
  USA: "🇺🇸",
  Uruguay: "🇺🇾",
  Venezuela: "🇻🇪",
  Wales: "🏴󠁧󠁢󠁷󠁬󠁳󠁿",
}

function teamFlag(name: string): string {
  return FLAGS[name] ?? ""
}

// ---------------------------------------------------------------------------
// Colour helpers
// ---------------------------------------------------------------------------

function probTextColor(p: number | null): string {
  if (p === null) return "text-slate-500"
  if (p >= 0.6) return "text-emerald-400"
  if (p >= 0.4) return "text-amber-400"
  return "text-rose-400"
}

function probBarColor(p: number | null): string {
  if (p === null) return "bg-slate-700"
  if (p >= 0.6) return "bg-emerald-500"
  if (p >= 0.4) return "bg-amber-500"
  return "bg-rose-500"
}

function formatDate(dateStr: string): string {
  try {
    return new Date(dateStr).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    })
  } catch {
    return dateStr
  }
}

// ---------------------------------------------------------------------------
// Templated match preview — pure logic, no LLM call
// ---------------------------------------------------------------------------

function buildPreview(match: Matchup): string | null {
  const { home, away, is_completed } = match
  if (is_completed) return null

  const hp = home.model_advance_prob
  const ap = away.model_advance_prob
  if (hp == null || ap == null) return null

  const favoured = hp >= ap ? home : away
  const underdog = hp >= ap ? away : home
  const favPct   = Math.round(Math.max(hp, ap) * 100)
  const gap      = Math.abs(hp - ap)

  const restNote = (() => {
    if (home.rest_days != null && away.rest_days != null) {
      const diff = home.rest_days - away.rest_days
      if (Math.abs(diff) >= 2) {
        const rested = diff > 0 ? home : away
        const tired  = diff > 0 ? away : home
        return ` ${tired.name} have had less time to recover (${tired.rest_days}d vs ${rested.rest_days}d rest).`
      }
    }
    return ""
  })()

  if (gap < 0.08) {
    return `A tight contest — our model sees this as close to a coin flip.${restNote}`
  }
  if (favPct >= 70) {
    return `${favoured.name} are strong favourites at ${favPct}% to advance over ${underdog.name}.${restNote}`
  }
  return `${favoured.name} hold a slight edge at ${favPct}% over ${underdog.name}.${restNote}`
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ProbRow({
  homeProb,
  label,
}: {
  homeProb: number | null
  label: string
}) {
  const homePct = homeProb != null ? Math.round(homeProb * 100) : null
  const awayPct = homePct != null ? 100 - homePct : null
  const barWidth = homePct ?? 50

  return (
    <div className="flex items-center gap-2.5">
      <span className="w-[4.5rem] text-[11px] text-slate-500 shrink-0">{label}</span>
      <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
        <div
          className={`h-full ${probBarColor(homeProb)} transition-[width] duration-500 ease-out`}
          style={{ width: `${barWidth}%` }}
        />
      </div>
      <span className={`w-8 text-right text-[11px] font-mono tabular-nums ${probTextColor(homeProb)}`}>
        {homePct != null ? `${homePct}%` : "—"}
      </span>
      <span className="text-slate-700 text-[11px]">/</span>
      <span className={`w-8 text-[11px] font-mono tabular-nums ${probTextColor(awayPct != null ? awayPct / 100 : null)}`}>
        {awayPct != null ? `${awayPct}%` : "—"}
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Lineup disclosure helpers
// ---------------------------------------------------------------------------

function ratingColor(pct: number): string {
  if (pct >= 0.75) return "text-emerald-400"
  if (pct >= 0.4)  return "text-slate-300"
  return "text-slate-500"
}

function LineupList({
  teamName,
  players,
}: {
  teamName: string
  players: PlayerSearchResult[]
}) {
  if (players.length === 0) {
    return (
      <div className="py-2 text-[11px] text-slate-600 italic">
        No player data for {teamName}
      </div>
    )
  }
  return (
    <div className="space-y-0.5">
      <p className="text-[10px] uppercase tracking-wider text-slate-600 mb-1">{teamName}</p>
      {players.map((p) => (
        <Link
          key={p.reep_id}
          href={`/players/${p.reep_id}`}
          className="flex items-center justify-between py-1 px-1.5 rounded hover:bg-slate-800 transition-colors group"
        >
          <span className="text-xs text-slate-400 group-hover:text-slate-100 truncate transition-colors">
            {p.name ?? p.reep_id}
          </span>
          <span className={`text-[11px] font-bold tabular-nums ml-2 shrink-0 ${ratingColor(p.percentile_rank)}`}>
            {p.posterior_mean.toFixed(2)}
          </span>
        </Link>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Animation variant (exported so MatchCardGrid can set the stagger container)
// ---------------------------------------------------------------------------

export const cardVariant = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.28, ease: "easeOut" as const } },
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

export default function MatchCard({ match }: { match: Matchup }) {
  const { home, away, is_completed, match_date } = match

  const [showLineups, setShowLineups] = useState(false)
  const [lineupsLoaded, setLineupsLoaded] = useState(false)
  const [lineupsLoading, setLineupsLoading] = useState(false)
  const [teamPlayers, setTeamPlayers] = useState<{
    home: PlayerSearchResult[]
    away: PlayerSearchResult[]
  } | null>(null)

  const loadLineups = useCallback(async () => {
    if (lineupsLoaded) return
    setLineupsLoading(true)
    try {
      const res = await fetch("/data/players.json", { cache: "force-cache" })
      if (!res.ok) return
      const all = (await res.json()) as PlayerResponse[]

      const byNat = (nat: string): PlayerSearchResult[] =>
        all
          .filter((p) => (p.national_team ?? p.nationality) === nat)
          .sort(
            (a, b) =>
              b.confidence_score - a.confidence_score ||
              b.posterior_mean - a.posterior_mean,
          )
          .slice(0, 10)
          .map((p) => ({
            reep_id:          p.reep_id,
            name:             p.name,
            nationality:      p.nationality,
            national_team:    p.national_team ?? null,
            position_micro:   p.position_micro,
            position_macro:   p.position_macro,
            posterior_mean:   p.posterior_mean,
            confidence_score: p.confidence_score,
            percentile_rank:  p.percentile_rank,
          }))

      setTeamPlayers({ home: byNat(home.name), away: byNat(away.name) })
      setLineupsLoaded(true)
    } catch { /* silent — data may not be available */ }
    finally { setLineupsLoading(false) }
  }, [lineupsLoaded, home.name, away.name])

  function toggleLineups() {
    if (!showLineups) loadLineups()
    setShowLineups((v) => !v)
  }

  const modelEdgeDelta =
    home.model_advance_prob != null && home.market_advance_prob != null
      ? home.model_advance_prob - home.market_advance_prob
      : null

  const showEdge = modelEdgeDelta != null && Math.abs(modelEdgeDelta) >= 0.03
  const preview  = buildPreview(match)

  return (
    <motion.div
      variants={cardVariant}
      className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col gap-4 hover:border-slate-700 transition-colors cursor-default"
    >
      {/* ── Header ────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-slate-500">{formatDate(match_date)}</span>
        {is_completed ? (
          <span className="flex items-center gap-1.5 text-[11px] font-medium text-emerald-500">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 shrink-0" />
            Full Time
          </span>
        ) : (
          <span className="flex items-center gap-1.5 text-[11px] text-slate-600">
            <span className="w-1.5 h-1.5 rounded-full bg-slate-600 shrink-0" />
            Scheduled
          </span>
        )}
      </div>

      {/* ── Teams ─────────────────────────────────────── */}
      <div className="flex items-center gap-3">
        {/* Home */}
        <div className="flex-1 min-w-0 flex flex-col gap-0.5">
          <span className="text-2xl leading-none">{teamFlag(home.name)}</span>
          <span className="text-sm font-semibold text-slate-100 truncate leading-snug">{home.name}</span>
          {home.rest_days != null && !is_completed && (
            <span
              className={`text-[10px] font-medium tabular-nums ${
                home.rest_days <= 2 ? "text-amber-500" : "text-slate-600"
              }`}
              title={`${home.rest_days}d since last match`}
            >
              {home.rest_days}d rest
            </span>
          )}
          {home.travel_km != null && !is_completed && (
            <span
              className={`text-[10px] font-medium tabular-nums ${
                home.travel_km >= 2000 ? "text-amber-500" : "text-slate-600"
              }`}
              title={`${home.travel_km.toLocaleString()} km travelled to this venue`}
            >
              {home.travel_km >= 1000
                ? `${(home.travel_km / 1000).toFixed(1)}k km`
                : `${home.travel_km} km`}
            </span>
          )}
        </div>

        {/* Score / vs */}
        <div className="shrink-0 text-center min-w-[2.5rem]">
          {is_completed && home.score != null && away.score != null ? (
            <span className="text-base font-bold text-slate-100 tabular-nums">
              {home.score}–{away.score}
            </span>
          ) : (
            <span className="text-xs text-slate-600 font-medium">vs</span>
          )}
        </div>

        {/* Away */}
        <div className="flex-1 min-w-0 flex flex-col items-end gap-0.5">
          <span className="text-2xl leading-none">{teamFlag(away.name)}</span>
          <span className="text-sm font-semibold text-slate-100 truncate text-right leading-snug">
            {away.name}
          </span>
          {away.rest_days != null && !is_completed && (
            <span
              className={`text-[10px] font-medium tabular-nums ${
                away.rest_days <= 2 ? "text-amber-500" : "text-slate-600"
              }`}
              title={`${away.rest_days}d since last match`}
            >
              {away.rest_days}d rest
            </span>
          )}
          {away.travel_km != null && !is_completed && (
            <span
              className={`text-[10px] font-medium tabular-nums ${
                away.travel_km >= 2000 ? "text-amber-500" : "text-slate-600"
              }`}
              title={`${away.travel_km.toLocaleString()} km travelled to this venue`}
            >
              {away.travel_km >= 1000
                ? `${(away.travel_km / 1000).toFixed(1)}k km`
                : `${away.travel_km} km`}
            </span>
          )}
        </div>
      </div>

      {/* ── Templated preview ─────────────────────────── */}
      {preview && (
        <p className="text-[11px] text-slate-500 leading-relaxed italic -mt-1">
          {preview}
        </p>
      )}

      {/* ── Probability bars ──────────────────────────── */}
      {(home.model_advance_prob != null || home.market_advance_prob != null) && (
        <div className="border-t border-slate-800 pt-3 space-y-2">
          <div className="flex justify-between text-[10px] text-slate-600 mb-1 px-[4.5rem]">
            <span>{home.abbrev ?? home.name.split(" ")[0]}</span>
            <span>{away.abbrev ?? away.name.split(" ")[0]}</span>
          </div>

          {home.model_advance_prob != null && (
            <ProbRow homeProb={home.model_advance_prob} label="Our model" />
          )}
          {home.market_advance_prob != null && (
            <ProbRow homeProb={home.market_advance_prob} label="Bookies" />
          )}

          {showEdge && (
            <p
              className={`text-[11px] font-medium pt-0.5 ${
                modelEdgeDelta! > 0 ? "text-emerald-500" : "text-rose-500"
              }`}
            >
              {modelEdgeDelta! > 0
                ? `Value pick: ${home.name.split(" ").at(-1)} +${Math.round(modelEdgeDelta! * 100)}% vs bookies`
                : `Value pick: ${away.name.split(" ").at(-1)} +${Math.round(Math.abs(modelEdgeDelta!) * 100)}% vs bookies`}
            </p>
          )}
        </div>
      )}
      {/* ── Lineups disclosure ────────────────────────── */}
      <div className="border-t border-slate-800 pt-3">
        <button
          onClick={toggleLineups}
          className="flex items-center gap-1.5 text-[11px] text-slate-600 hover:text-slate-400 transition-colors"
        >
          <svg
            viewBox="0 0 16 16"
            fill="currentColor"
            className={`w-3 h-3 transition-transform ${showLineups ? "rotate-90" : ""}`}
          >
            <path
              fillRule="evenodd"
              d="M6.22 4.22a.75.75 0 0 1 1.06 0l3.25 3.25a.75.75 0 0 1 0 1.06l-3.25 3.25a.75.75 0 0 1-1.06-1.06L8.94 8 6.22 5.28a.75.75 0 0 1 0-1.06Z"
              clipRule="evenodd"
            />
          </svg>
          {lineupsLoading ? "Loading…" : "Lineups"}
        </button>

        <AnimatePresence>
          {showLineups && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.22, ease: "easeOut" }}
              className="overflow-hidden"
            >
              <div className="mt-3 grid grid-cols-2 gap-4">
                <LineupList
                  teamName={home.name}
                  players={teamPlayers?.home ?? []}
                />
                <LineupList
                  teamName={away.name}
                  players={teamPlayers?.away ?? []}
                />
              </div>
              {!lineupsLoaded && !lineupsLoading && (
                <p className="text-[11px] text-slate-600 mt-2 italic">
                  No player data available yet.
                </p>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  )
}
