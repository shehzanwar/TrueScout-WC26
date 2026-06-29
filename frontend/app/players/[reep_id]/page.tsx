import { notFound } from "next/navigation"
import Link from "next/link"
import { getPlayer } from "@/lib/server-data"
import PlayerRadar from "./PlayerRadar"
import TacticalAnalysis from "./TacticalAnalysis"
import RawStats from "./RawStats"
import MatchTimeline from "./MatchTimeline"

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getOrdinalSuffix(n: number): string {
  const abs    = Math.abs(n)
  const mod100 = abs % 100
  if (mod100 >= 11 && mod100 <= 13) return `${n}th`
  const mod10 = abs % 10
  if (mod10 === 1) return `${n}st`
  if (mod10 === 2) return `${n}nd`
  if (mod10 === 3) return `${n}rd`
  return `${n}th`
}

function ConfidenceBadge({ score }: { score: number }) {
  if (score >= 0.7) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
        Reliable data
      </span>
    )
  }
  if (score >= 0.4) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-500/15 text-amber-400 border border-amber-500/20">
        <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
        Some data
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-rose-500/15 text-rose-400 border border-rose-500/20">
      <span className="w-1.5 h-1.5 rounded-full bg-rose-400 shrink-0" />
      Limited data
    </span>
  )
}

function StatRow({
  label,
  value,
  sub,
}: {
  label: string
  value: string
  sub?: string
}) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-slate-800 last:border-0">
      <span className="text-xs text-slate-500">{label}</span>
      <div className="text-right">
        <span className="text-sm font-semibold text-slate-100 tabular-nums">{value}</span>
        {sub && <span className="text-xs text-slate-600 ml-1.5">{sub}</span>}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Breadcrumb chevron
// ---------------------------------------------------------------------------

function Chevron() {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" className="w-3 h-3 text-slate-700 shrink-0">
      <path
        fillRule="evenodd"
        d="M6.22 4.22a.75.75 0 0 1 1.06 0l3.25 3.25a.75.75 0 0 1 0 1.06l-3.25 3.25a.75.75 0 0 1-1.06-1.06L8.94 8 6.22 5.28a.75.75 0 0 1 0-1.06Z"
        clipRule="evenodd"
      />
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Page (Server Component)
// ---------------------------------------------------------------------------

export default async function PlayerProfilePage({
  params,
}: {
  params: Promise<{ reep_id: string }>
}) {
  const { reep_id } = await params
  const player = await getPlayer(reep_id).catch(() => null)

  if (!player) notFound()

  const hdiLow      = player.hdi_low.toFixed(2)
  const hdiHigh     = player.hdi_high.toFixed(2)
  const clubPct     = `${Math.round(player.shrinkage_weight * 100)}%`
  const wcPct       = `${Math.round((1 - player.shrinkage_weight) * 100)}%`
  const pctRank     = Math.round(player.percentile_rank * 100)
  const pctLabel    = pctRank >= 90
    ? "Top 10%"
    : pctRank >= 75
    ? "Top 25%"
    : pctRank >= 50
    ? "Above Average"
    : "Below Average"

  const archetypeLabel =
    player.cluster_id === -1 || !player.cluster_label
      ? (player.position_detail ?? player.position_micro ?? player.position_macro)
      : player.cluster_label

  // Position group label for "Rank among Xes" line
  const positionGroupLabel = (() => {
    const micro = player.position_micro ?? player.position_macro ?? ""
    const endings: Record<string, string> = {
      GK: "goalkeepers", CB: "centre-backs", LB: "left-backs", RB: "right-backs",
      WB: "wing-backs", DM: "defensive mids", CM: "central mids", AM: "attacking mids",
      LW: "left wingers", RW: "right wingers", SS: "second strikers", CF: "strikers",
    }
    return endings[micro] ?? `${micro}s`
  })()

  return (
    <div className="max-w-4xl mx-auto space-y-6">

      {/* ── Breadcrumb ─────────────────────────────────────────────── */}
      <nav className="flex items-center gap-1.5 text-xs">
        <Link
          href="/players"
          className="text-slate-500 hover:text-slate-300 transition-colors"
        >
          Players
        </Link>
        {player.nationality && (
          <>
            <Chevron />
            <Link
              href={`/players?q=${encodeURIComponent(player.nationality)}`}
              className="text-slate-500 hover:text-slate-300 transition-colors"
            >
              {player.nationality}
            </Link>
          </>
        )}
        <Chevron />
        <span className="text-slate-300 truncate max-w-[16rem]">
          {player.name ?? reep_id}
        </span>
      </nav>

      {/* ── Header ─────────────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">
            {player.name ?? reep_id}
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            {[
              player.nationality,
              player.position_detail ?? player.position_macro,
              archetypeLabel,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
        <ConfidenceBadge score={player.confidence_score} />
      </div>

      {/* ── Two-column grid ────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">

        {/* Rating breakdown card */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-1">
          <h2 className="text-sm font-semibold text-slate-100 uppercase tracking-wider mb-3">
            Rating Breakdown
          </h2>

          <StatRow
            label="Overall Rating"
            value={player.posterior_mean.toFixed(2)}
            sub={pctLabel}
          />
          <StatRow
            label="Rating Range"
            value={`${hdiLow} – ${hdiHigh}`}
            sub={`likely between these two values`}
          />
          <StatRow
            label="From club (last 2 seasons)"
            value={player.prior_mean.toFixed(2)}
            sub={`${clubPct} of rating`}
          />
          <StatRow
            label="From World Cup form"
            value={wcPct}
            sub={`${Math.round(player.wc_minutes)} min played`}
          />
          <StatRow
            label={`Rank among ${positionGroupLabel}`}
            value={getOrdinalSuffix(pctRank)}
            sub={`percentile`}
          />
          <StatRow
            label="Player Style"
            value={archetypeLabel ?? player.position_macro}
            sub={player.position_bucket}
          />

          {/* Club Form vs WC Form bar */}
          <div className="pt-3 space-y-2">
            <div className="flex justify-between text-[11px] text-slate-500 mb-1">
              <span>Club form</span>
              <span>World Cup form</span>
            </div>
            <div className="h-2 bg-slate-800 rounded-full overflow-hidden flex">
              <div
                className="h-full bg-slate-600 rounded-l-full"
                style={{ width: `${Math.round(player.shrinkage_weight * 100)}%` }}
              />
              <div
                className="h-full bg-emerald-500"
                style={{ width: `${Math.round((1 - player.shrinkage_weight) * 100)}%` }}
              />
            </div>
            <div className="flex justify-between text-[11px]">
              <span className="text-slate-600">{clubPct} club</span>
              <span className="text-emerald-500">{wcPct} WC</span>
            </div>
          </div>
        </div>

        {/* Radar chart */}
        <PlayerRadar radar={player.radar} />
      </div>

      {/* ── Raw Stats ──────────────────────────────────────────────── */}
      <RawStats player={player} />

      {/* ── Match Timeline ─────────────────────────────────────────── */}
      <MatchTimeline player={player} />

      {/* ── Tactical Analysis ──────────────────────────────────────── */}
      <TacticalAnalysis reepId={reep_id} />

    </div>
  )
}
