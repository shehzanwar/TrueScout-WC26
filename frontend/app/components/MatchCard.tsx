"use client"

import { motion } from "framer-motion"
import type { Matchup } from "@/lib/api"

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

  const modelEdgeDelta =
    home.model_advance_prob != null && home.market_advance_prob != null
      ? home.model_advance_prob - home.market_advance_prob
      : null

  const showEdge = modelEdgeDelta != null && Math.abs(modelEdgeDelta) >= 0.03

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
        </div>
      </div>

      {/* ── Probability bars ──────────────────────────── */}
      {(home.model_advance_prob != null || home.market_advance_prob != null) && (
        <div className="border-t border-slate-800 pt-3 space-y-2">
          <div className="flex justify-between text-[10px] text-slate-600 mb-1 px-[4.5rem]">
            <span>{home.abbrev ?? home.name.split(" ")[0]}</span>
            <span>{away.abbrev ?? away.name.split(" ")[0]}</span>
          </div>

          {home.model_advance_prob != null && (
            <ProbRow homeProb={home.model_advance_prob} label="TrueScout" />
          )}
          {home.market_advance_prob != null && (
            <ProbRow homeProb={home.market_advance_prob} label="Market" />
          )}

          {showEdge && (
            <p
              className={`text-[11px] font-medium pt-0.5 ${
                modelEdgeDelta! > 0 ? "text-emerald-500" : "text-rose-500"
              }`}
            >
              {modelEdgeDelta! > 0
                ? `Edge: ${home.name.split(" ").at(-1)} +${Math.round(modelEdgeDelta! * 100)}% vs market`
                : `Edge: ${away.name.split(" ").at(-1)} +${Math.round(Math.abs(modelEdgeDelta!) * 100)}% vs market`}
            </p>
          )}
        </div>
      )}
    </motion.div>
  )
}
