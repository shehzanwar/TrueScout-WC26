"use client"

import { motion } from "framer-motion"
import type { BrierSummary } from "@/lib/api"

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmt(v: number | null, decimals = 4): string {
  return v === null ? "—" : v.toFixed(decimals)
}

function skillPct(v: number | null): string {
  if (v === null) return "—"
  const pct = v * 100
  return (pct >= 0 ? "+" : "") + pct.toFixed(1) + "%"
}

// Color for the MODEL value: emerald if beating market, rose if losing, slate if no market
function modelColor(model: number | null, market: number | null): string {
  if (model === null) return "text-slate-500"
  if (market === null) return "text-slate-300"
  return model < market ? "text-emerald-400" : "text-rose-400"
}

function skillColor(v: number | null): string {
  if (v === null) return "text-slate-500"
  return v >= 0 ? "text-emerald-400" : "text-rose-400"
}

// ---------------------------------------------------------------------------
// Reusable card shell
// ---------------------------------------------------------------------------

function Card({ children, delay = 0 }: { children: React.ReactNode; delay?: number }) {
  return (
    <motion.div
      className="bg-slate-900 border border-slate-800 rounded-xl p-5"
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay, ease: "easeOut" as const }}
    >
      {children}
    </motion.div>
  )
}

// ---------------------------------------------------------------------------
// Metric row: label | value
// ---------------------------------------------------------------------------

function MetricRow({
  label,
  value,
  valueClass = "text-slate-300",
  sub,
}: {
  label: string
  value: string
  valueClass?: string
  sub?: string
}) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-slate-800 last:border-0">
      <span className="text-xs text-slate-500">{label}</span>
      <div className="text-right">
        <span className={`text-sm font-bold tabular-nums ${valueClass}`}>{value}</span>
        {sub && <span className="text-xs text-slate-600 ml-1.5">{sub}</span>}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Exported SummaryCards
// ---------------------------------------------------------------------------

export default function SummaryCards({ s }: { s: BrierSummary }) {
  const hasData = s.n_matches > 0

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">

      {/* ── Brier Score ─────────────────────────────────────────────── */}
      <Card delay={0}>
        <div className="flex items-start justify-between mb-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Brier Score
            </p>
            <p className="text-[10px] text-slate-700 mt-0.5">lower = better · max 0.25</p>
          </div>
          {hasData && s.avg_brier_model !== null && s.avg_brier_model < s.coin_flip_brier && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-500 border border-emerald-500/20 shrink-0">
              Beating baseline
            </span>
          )}
        </div>

        <MetricRow
          label="TrueScout"
          value={fmt(s.avg_brier_model)}
          valueClass={modelColor(s.avg_brier_model, s.avg_brier_market)}
        />
        <MetricRow
          label="Market"
          value={fmt(s.avg_brier_market)}
          valueClass={s.avg_brier_market === null ? "text-slate-600" : "text-slate-300"}
        />
        <MetricRow
          label="Coin-Flip"
          value={fmt(s.coin_flip_brier)}
          valueClass="text-slate-600"
          sub="baseline"
        />
      </Card>

      {/* ── Skill Score ─────────────────────────────────────────────── */}
      <Card delay={0.06}>
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-3">
          Brier Skill Score
        </p>

        <div className="flex flex-col items-center justify-center py-3 gap-1">
          <span className={`text-3xl font-black tabular-nums tracking-tight ${skillColor(s.brier_skill_vs_coin)}`}>
            {skillPct(s.brier_skill_vs_coin)}
          </span>
          <span className="text-[11px] text-slate-600 text-center">vs coin-flip baseline</span>
        </div>

        {s.brier_skill_vs_market !== null && (
          <div className="mt-2 pt-2 border-t border-slate-800 flex items-center justify-between">
            <span className="text-xs text-slate-500">vs market</span>
            <span className={`text-sm font-bold tabular-nums ${skillColor(s.brier_skill_vs_market)}`}>
              {skillPct(s.brier_skill_vs_market)}
            </span>
          </div>
        )}
      </Card>

      {/* ── Log Loss ────────────────────────────────────────────────── */}
      <Card delay={0.12}>
        <div className="mb-3">
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Log Loss
          </p>
          <p className="text-[10px] text-slate-700 mt-0.5">lower = better · ln(2) ≈ 0.693</p>
        </div>

        <MetricRow
          label="TrueScout"
          value={fmt(s.avg_log_loss_model)}
          valueClass={modelColor(s.avg_log_loss_model, s.avg_log_loss_market)}
        />
        <MetricRow
          label="Market"
          value={fmt(s.avg_log_loss_market)}
          valueClass={s.avg_log_loss_market === null ? "text-slate-600" : "text-slate-300"}
        />
        <MetricRow
          label="Coin-Flip"
          value={fmt(s.coin_flip_log_loss)}
          valueClass="text-slate-600"
          sub="baseline"
        />
      </Card>

      {/* ── Matches Graded ──────────────────────────────────────────── */}
      <Card delay={0.18}>
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-3">
          Matches Graded
        </p>

        <div className="flex flex-col items-center justify-center py-3 gap-1">
          <span className="text-4xl font-black text-slate-100 tabular-nums">
            {s.n_matches}
          </span>
          <span className="text-[11px] text-slate-600">knockout matches</span>
        </div>

        <div className="pt-2 border-t border-slate-800 flex items-center justify-between">
          <span className="text-xs text-slate-500">With market odds</span>
          <span className="text-sm font-bold text-slate-300">{s.n_with_market}</span>
        </div>
      </Card>
    </div>
  )
}
