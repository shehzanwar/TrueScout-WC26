import { notFound } from "next/navigation"
import Link from "next/link"
import { getPlayer } from "@/lib/server-data"
import PlayerRadar from "./PlayerRadar"
import TacticalAnalysis from "./TacticalAnalysis"

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function ConfidenceBadge({ score }: { score: number }) {
  if (score >= 0.7) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
        High Confidence Data
      </span>
    )
  }
  if (score >= 0.4) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-500/15 text-amber-400 border border-amber-500/20">
        <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
        Moderate Data
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-rose-500/15 text-rose-400 border border-rose-500/20">
      <span className="w-1.5 h-1.5 rounded-full bg-rose-400 shrink-0" />
      Sparse / Traditional Scout
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

  const hdiRange = `${player.hdi_low.toFixed(2)} – ${player.hdi_high.toFixed(2)}`
  const shrinkagePct = `${Math.round(player.shrinkage_weight * 100)}%`
  const wcPct = `${Math.round((1 - player.shrinkage_weight) * 100)}%`
  const pctLabel = player.percentile_rank >= 0.9
    ? "Top 10%"
    : player.percentile_rank >= 0.75
    ? "Top 25%"
    : player.percentile_rank >= 0.5
    ? "Above median"
    : "Below median"

  return (
    <div className="max-w-4xl mx-auto space-y-6">

      {/* ── Back link ──────────────────────────────────────────────── */}
      <Link
        href="/players"
        className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-300 transition-colors"
      >
        <svg viewBox="0 0 16 16" fill="currentColor" className="w-3.5 h-3.5">
          <path
            fillRule="evenodd"
            d="M9.78 4.22a.75.75 0 0 1 0 1.06L7.06 8l2.72 2.72a.75.75 0 1 1-1.06 1.06L5.47 8.53a.75.75 0 0 1 0-1.06l3.25-3.25a.75.75 0 0 1 1.06 0Z"
            clipRule="evenodd"
          />
        </svg>
        Player Search
      </Link>

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
              player.cluster_label,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
        <ConfidenceBadge score={player.confidence_score} />
      </div>

      {/* ── Two-column grid ────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">

        {/* Bayesian stats */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-1">
          <h2 className="text-sm font-semibold text-slate-100 uppercase tracking-wider mb-3">
            Bayesian Posterior
          </h2>

          <StatRow
            label="Posterior rating"
            value={player.posterior_mean.toFixed(3)}
            sub={pctLabel}
          />
          <StatRow
            label="90% HDI"
            value={hdiRange}
            sub={`±${player.posterior_std.toFixed(3)}`}
          />
          <StatRow
            label="Club prior"
            value={player.prior_mean.toFixed(3)}
            sub={`${shrinkagePct} weight`}
          />
          <StatRow
            label="WC data weight"
            value={wcPct}
            sub={`${Math.round(player.wc_minutes)} min`}
          />
          <StatRow
            label="Position percentile"
            value={`${Math.round(player.percentile_rank * 100)}th`}
            sub={player.position_micro ?? player.position_macro}
          />
          <StatRow
            label="Archetype"
            value={player.cluster_label ?? `Cluster ${player.cluster_id}`}
            sub={player.position_bucket}
          />


          {/* Posterior vs Prior bar */}
          <div className="pt-3 space-y-2">
            <div className="flex justify-between text-[11px] text-slate-500 mb-1">
              <span>Prior weight (club data)</span>
              <span>WC data weight</span>
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
              <span className="text-slate-600">{shrinkagePct} prior</span>
              <span className="text-emerald-500">{wcPct} WC</span>
            </div>
          </div>
        </div>

        {/* Radar chart */}
        <PlayerRadar radar={player.radar} />
      </div>

      {/* ── Tactical Analysis ──────────────────────────────────────── */}
      <TacticalAnalysis reepId={reep_id} />

    </div>
  )
}
