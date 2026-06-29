"use client"

import { motion } from "framer-motion"
import type { SimTeam, BrierSummary, BrierEntry } from "@/lib/api"

// ---------------------------------------------------------------------------
// Animation variants
// ---------------------------------------------------------------------------

const container = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.08 },
  },
}

const card = {
  hidden: { opacity: 0, y: 18 },
  show: { opacity: 1, y: 0, transition: { duration: 0.35, ease: "easeOut" as const } },
}

const row = {
  hidden: { opacity: 0, x: -8 },
  show: { opacity: 1, x: 0, transition: { duration: 0.25, ease: "easeOut" as const } },
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatPill({
  value,
  label,
  accent = false,
}: {
  value: string
  label: string
  accent?: boolean
}) {
  return (
    <div className="flex flex-col items-center gap-0.5">
      <span className={`text-lg font-bold tabular-nums ${accent ? "text-emerald-400" : "text-slate-100"}`}>
        {value}
      </span>
      <span className="text-xs text-slate-500 uppercase tracking-wide">{label}</span>
    </div>
  )
}

function SectionCard({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle?: string
  children: React.ReactNode
}) {
  return (
    <motion.div
      variants={card}
      className="bg-slate-900 border border-slate-800 rounded-xl p-5 flex flex-col gap-4"
    >
      <div>
        <h2 className="text-sm font-semibold text-slate-100 uppercase tracking-wider">{title}</h2>
        {subtitle && <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>}
      </div>
      {children}
    </motion.div>
  )
}

// ---------------------------------------------------------------------------
// Title Favorites leaderboard
// ---------------------------------------------------------------------------

function FavoritesCard({ champions }: { champions: SimTeam[] }) {
  const top5 = champions
    .slice()
    .sort((a, b) => b.title_prob - a.title_prob)
    .slice(0, 5)

  const maxProb = top5[0]?.title_prob ?? 1

  return (
    <SectionCard
      title="Title Favorites"
      subtitle="Top 5 by Monte Carlo title probability"
    >
      <motion.ol variants={container} initial="hidden" animate="show" className="space-y-2.5">
        {top5.map((team, i) => {
          const pct = ((team.title_prob / maxProb) * 100).toFixed(0)
          return (
            <motion.li key={team.team_id} variants={row} className="flex items-center gap-3">
              <span className="w-5 text-center text-xs font-bold text-slate-600 tabular-nums">
                {i + 1}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex justify-between items-baseline mb-1">
                  <span className="text-sm font-medium text-slate-200 truncate">
                    {team.team_id}
                  </span>
                  <span className="text-xs font-mono text-emerald-400 shrink-0 ml-2">
                    {(team.title_prob * 100).toFixed(1)}%
                  </span>
                </div>
                <div className="h-1 bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-emerald-500 rounded-full"
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
            </motion.li>
          )
        })}
      </motion.ol>
    </SectionCard>
  )
}

// ---------------------------------------------------------------------------
// Brier calibration card
// ---------------------------------------------------------------------------

function CalibrationCard({
  summary,
  entries,
}: {
  summary: BrierSummary
  entries: BrierEntry[]
}) {
  const skillPct =
    summary.brier_skill_vs_coin != null
      ? `${(summary.brier_skill_vs_coin * 100).toFixed(1)}%`
      : "—"

  const brierModel =
    summary.avg_brier_model != null
      ? summary.avg_brier_model.toFixed(4)
      : "—"

  const skillPositive =
    summary.brier_skill_vs_coin != null && summary.brier_skill_vs_coin > 0

  return (
    <SectionCard
      title="Model Calibration"
      subtitle="Brier score vs 50/50 coin-flip baseline"
    >
      {summary.n_matches === 0 ? (
        <p className="text-sm text-slate-500 italic">
          No completed knockout matches graded yet.
        </p>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-3 py-1">
            <StatPill value={String(summary.n_matches)} label="Graded" />
            <StatPill value={brierModel} label="Brier" accent />
            <StatPill
              value={skillPct}
              label="Skill"
              accent={skillPositive}
            />
          </div>

          {/* Skill score bar */}
          {summary.brier_skill_vs_coin != null && (
            <div>
              <div className="flex justify-between text-xs text-slate-500 mb-1">
                <span>vs Coin-flip baseline</span>
                <span className={skillPositive ? "text-emerald-400" : "text-rose-400"}>
                  {skillPositive ? "▲ better" : "▼ worse"}
                </span>
              </div>
              <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${skillPositive ? "bg-emerald-500" : "bg-rose-500"}`}
                  style={{
                    width: `${Math.min(Math.abs(summary.brier_skill_vs_coin) * 100 * 2, 100)}%`,
                  }}
                />
              </div>
            </div>
          )}

          {/* Recent graded matches */}
          {entries.length > 0 && (
            <div className="border-t border-slate-800 pt-3 space-y-1.5">
              <p className="text-xs text-slate-500 uppercase tracking-wide">Recent results</p>
              {entries.slice(0, 3).map((e) => (
                <div key={e.event_id} className="flex items-center justify-between text-xs">
                  <span className="text-slate-400">
                    {e.home_team} <span className="text-slate-600">vs</span> {e.away_team}
                  </span>
                  <span className="text-slate-500 font-mono">
                    Brier {e.brier_model?.toFixed(3) ?? "—"}
                  </span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </SectionCard>
  )
}

// ---------------------------------------------------------------------------
// Main export — receives data from Server Component
// ---------------------------------------------------------------------------

export default function HomeCards({
  champions,
  brierSummary,
  brierEntries,
}: {
  champions: SimTeam[]
  brierSummary: BrierSummary
  brierEntries: BrierEntry[]
}) {
  return (
    <motion.div
      variants={container}
      initial="hidden"
      animate="show"
      className="grid grid-cols-1 lg:grid-cols-2 gap-5"
    >
      <FavoritesCard champions={champions} />
      <CalibrationCard summary={brierSummary} entries={brierEntries} />
    </motion.div>
  )
}
