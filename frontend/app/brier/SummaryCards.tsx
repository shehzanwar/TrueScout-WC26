"use client"

import { useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import type { BrierSummary } from "@/lib/api"
import { LabelWithInfo } from "@/app/components/Tooltip"

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
      initial={{ y: 5 }}
      animate={{ y: 0 }}
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
  const [showAdvanced, setShowAdvanced] = useState(false)

  return (
    <div className="space-y-4">
      {/* ── 3-card visible row ───────────────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">

        {/* ── Prediction Accuracy (was: Brier Score) ─────────────────── */}
        <Card delay={0}>
          <div className="flex items-start justify-between mb-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                <LabelWithInfo
                  label="Prediction Accuracy"
                  tip="Lower is better. A random coin-flip scores 0.25. We aim below 0.20."
                />
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
            label="Our model"
            value={fmt(s.avg_brier_model)}
            valueClass={modelColor(s.avg_brier_model, s.avg_brier_market)}
          />
          <MetricRow
            label="Bookies"
            value={fmt(s.avg_brier_market)}
            valueClass={s.avg_brier_market === null ? "text-slate-600" : "text-slate-300"}
          />
          <MetricRow
            label="Coin-flip"
            value={fmt(s.coin_flip_brier)}
            valueClass="text-slate-600"
            sub="baseline"
          />
        </Card>

        {/* ── Edge over coin-flip (was: Brier Skill Score) ───────────── */}
        <Card delay={0.06}>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-3">
            <LabelWithInfo
              label="Edge over coin-flip"
              tip="How much better than random chance our predictions are. Positive means we're beating a coin-flip."
            />
          </p>

          <div className="flex flex-col items-center justify-center py-3 gap-1">
            <span className={`text-3xl font-black tabular-nums tracking-tight ${skillColor(s.brier_skill_vs_coin)}`}>
              {skillPct(s.brier_skill_vs_coin)}
            </span>
            <span className="text-[11px] text-slate-600 text-center">vs coin-flip baseline</span>
          </div>

          {s.brier_skill_vs_market !== null && (
            <div className="mt-2 pt-2 border-t border-slate-800 flex items-center justify-between">
              <span className="text-xs text-slate-500">vs bookies</span>
              <span className={`text-sm font-bold tabular-nums ${skillColor(s.brier_skill_vs_market)}`}>
                {skillPct(s.brier_skill_vs_market)}
              </span>
            </div>
          )}
        </Card>

        {/* ── Matches Graded ──────────────────────────────────────────── */}
        <Card delay={0.12}>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-3">
            Matches Graded
          </p>

          <div className="flex flex-col items-center justify-center py-3 gap-1">
            <span className="text-4xl font-black text-slate-100 tabular-nums">
              {s.n_matches}
            </span>
            <span className="text-[11px] text-slate-600">knockout matches</span>
          </div>

          <div className="pt-2 border-t border-slate-800 space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-500">Correct direction</span>
              <span className="text-sm font-bold tabular-nums text-slate-300">
                {s.n_correct}/{s.n_matches}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-500">With bookmaker odds</span>
              <span className="text-sm font-bold text-slate-300">{s.n_with_market}</span>
            </div>
          </div>
        </Card>
      </div>

      {/* ── Advanced collapsible (Log Loss) ─────────────────────────── */}
      <div>
        <button
          onClick={() => setShowAdvanced((v) => !v)}
          className="flex items-center gap-1.5 text-xs text-slate-600 hover:text-slate-400 transition-colors"
        >
          <svg
            viewBox="0 0 16 16"
            fill="currentColor"
            className={`w-3.5 h-3.5 transition-transform ${showAdvanced ? "rotate-90" : ""}`}
          >
            <path
              fillRule="evenodd"
              d="M6.22 4.22a.75.75 0 0 1 1.06 0l3.25 3.25a.75.75 0 0 1 0 1.06l-3.25 3.25a.75.75 0 0 1-1.06-1.06L8.94 8 6.22 5.28a.75.75 0 0 1 0-1.06Z"
              clipRule="evenodd"
            />
          </svg>
          Advanced metrics
        </button>

        <AnimatePresence>
          {showAdvanced && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.22, ease: "easeOut" }}
              className="overflow-hidden mt-3"
            >
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {/* Log Loss */}
                <Card delay={0}>
                  <div className="mb-3">
                    <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                      Log Loss
                    </p>
                    <p className="text-[10px] text-slate-700 mt-0.5">lower = better · ln(2) ≈ 0.693</p>
                  </div>

                  <MetricRow
                    label="Our model"
                    value={fmt(s.avg_log_loss_model)}
                    valueClass={modelColor(s.avg_log_loss_model, s.avg_log_loss_market)}
                  />
                  <MetricRow
                    label="Bookies"
                    value={fmt(s.avg_log_loss_market)}
                    valueClass={s.avg_log_loss_market === null ? "text-slate-600" : "text-slate-300"}
                  />
                  <MetricRow
                    label="Coin-flip"
                    value={fmt(s.coin_flip_log_loss)}
                    valueClass="text-slate-600"
                    sub="baseline"
                  />
                </Card>

                {/* Info card explaining Log Loss */}
                <div className="bg-slate-900/50 border border-slate-800/60 rounded-xl p-5 flex flex-col justify-center gap-2">
                  <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">About log loss</p>
                  <p className="text-xs text-slate-600 leading-relaxed">
                    Log Loss penalises overconfident wrong predictions more harshly than Brier Score.
                    It measures the same thing in a different mathematical space.
                    Both metrics paint the same picture — Log Loss is useful for comparing
                    against academic benchmarks.
                  </p>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}
