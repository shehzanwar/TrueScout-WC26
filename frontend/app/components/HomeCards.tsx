"use client"

import Link from "next/link"
import { motion } from "framer-motion"
import type { SimTeam, BrierSummary, BrierEntry, Matchup, PlayerResponse, InsightsOvernight } from "@/lib/api"

// ---------------------------------------------------------------------------
// Animation variants
// ---------------------------------------------------------------------------

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.07 } },
}

const card = {
  hidden: { opacity: 0, y: 18 },
  show: { opacity: 1, y: 0, transition: { duration: 0.32, ease: "easeOut" as const } },
}

const row = {
  hidden: { opacity: 0, x: -8 },
  show: { opacity: 1, x: 0, transition: { duration: 0.25, ease: "easeOut" as const } },
}

// ---------------------------------------------------------------------------
// Shared
// ---------------------------------------------------------------------------

const FLAGS: Record<string, string> = {
  Argentina: "🇦🇷", Australia: "🇦🇺", Belgium: "🇧🇪", Bolivia: "🇧🇴",
  Brazil: "🇧🇷", Cameroon: "🇨🇲", Canada: "🇨🇦", Chile: "🇨🇱",
  Colombia: "🇨🇴", "Costa Rica": "🇨🇷", Croatia: "🇭🇷", Denmark: "🇩🇰",
  Ecuador: "🇪🇨", Egypt: "🇪🇬", England: "🏴󠁧󠁢󠁥󠁮󠁧󠁿", France: "🇫🇷",
  Germany: "🇩🇪", Ghana: "🇬🇭", Honduras: "🇭🇳", Hungary: "🇭🇺",
  Indonesia: "🇮🇩", Iran: "🇮🇷", Japan: "🇯🇵", "Korea Republic": "🇰🇷",
  Mexico: "🇲🇽", Morocco: "🇲🇦", Netherlands: "🇳🇱", "New Zealand": "🇳🇿",
  Nigeria: "🇳🇬", Panama: "🇵🇦", Paraguay: "🇵🇾", Peru: "🇵🇪",
  Poland: "🇵🇱", Portugal: "🇵🇹", Qatar: "🇶🇦", Romania: "🇷🇴",
  "Saudi Arabia": "🇸🇦", Scotland: "🏴󠁧󠁢󠁳󠁣󠁴󠁿", Senegal: "🇸🇳",
  Serbia: "🇷🇸", Slovenia: "🇸🇮", Spain: "🇪🇸", Switzerland: "🇨🇭",
  Tunisia: "🇹🇳", Türkiye: "🇹🇷", Ukraine: "🇺🇦", "United States": "🇺🇸",
  Uruguay: "🇺🇾", Venezuela: "🇻🇪", Wales: "🏴󠁧󠁢󠁷󠁬󠁳󠁿", "Congo DR": "🇨🇩",
}
const flag = (n: string) => FLAGS[n] ?? ""

function StatPill({ value, label, accent = false }: { value: string; label: string; accent?: boolean }) {
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
  title, subtitle, children,
}: {
  title: string; subtitle?: string; children: React.ReactNode
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
// Title Favorites
// ---------------------------------------------------------------------------

function FavoritesCard({ champions }: { champions: SimTeam[] }) {
  const top5 = champions.slice().sort((a, b) => b.title_prob - a.title_prob).slice(0, 5)
  const maxProb = top5[0]?.title_prob ?? 1
  return (
    <SectionCard title="Title Favorites" subtitle="Chance of winning the World Cup">
      {top5.length === 0 ? (
        <p className="text-sm text-slate-500 italic">No simulation data yet.</p>
      ) : (
        <motion.ol variants={container} initial="hidden" animate="show" className="space-y-2.5">
          {top5.map((team, i) => (
            <motion.li key={team.team_id} variants={row} className="flex items-center gap-3">
              <span className="w-5 text-center text-xs font-bold text-slate-600 tabular-nums">{i + 1}</span>
              <div className="flex-1 min-w-0">
                <div className="flex justify-between items-baseline mb-1">
                  <span className="text-sm font-medium text-slate-200 truncate">{team.team_id}</span>
                  <span className="text-xs font-mono text-emerald-400 shrink-0 ml-2">
                    {(team.title_prob * 100).toFixed(1)}%
                  </span>
                </div>
                <div className="h-1 bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-emerald-500 rounded-full"
                    style={{ width: `${((team.title_prob / maxProb) * 100).toFixed(0)}%` }}
                  />
                </div>
              </div>
            </motion.li>
          ))}
        </motion.ol>
      )}
    </SectionCard>
  )
}

// ---------------------------------------------------------------------------
// Prediction Accuracy (Brier)
// ---------------------------------------------------------------------------

function CalibrationCard({ summary, entries }: { summary: BrierSummary; entries: BrierEntry[] }) {
  const skillPct  = summary.brier_skill_vs_coin != null ? `${(summary.brier_skill_vs_coin * 100).toFixed(1)}%` : "—"
  const brierModel = summary.avg_brier_model != null ? summary.avg_brier_model.toFixed(4) : "—"
  const skillPos  = summary.brier_skill_vs_coin != null && summary.brier_skill_vs_coin > 0

  return (
    <SectionCard title="Prediction Accuracy" subtitle="How well our model calls knockout results">
      {summary.n_matches === 0 ? (
        <p className="text-sm text-slate-500 italic">No completed knockout matches graded yet.</p>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-3 py-1">
            <StatPill value={String(summary.n_matches)} label="Graded" />
            <StatPill value={brierModel} label="Accuracy" accent />
            <StatPill value={skillPct} label="Edge" accent={skillPos} />
          </div>
          {summary.brier_skill_vs_coin != null && (
            <div>
              <div className="flex justify-between text-xs text-slate-500 mb-1">
                <span>vs coin-flip</span>
                <span className={skillPos ? "text-emerald-400" : "text-rose-400"}>
                  {skillPos ? "▲ better" : "▼ worse"}
                </span>
              </div>
              <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${skillPos ? "bg-emerald-500" : "bg-rose-500"}`}
                  style={{ width: `${Math.min(Math.abs(summary.brier_skill_vs_coin) * 200, 100)}%` }}
                />
              </div>
            </div>
          )}
          {entries.length > 0 && (
            <div className="border-t border-slate-800 pt-3 space-y-1.5">
              <p className="text-xs text-slate-500 uppercase tracking-wide">Recent results</p>
              {entries.slice(0, 3).map((e) => (
                <div key={e.event_id} className="flex items-center justify-between text-xs">
                  <span className="text-slate-400">
                    {e.home_team} <span className="text-slate-600">vs</span> {e.away_team}
                  </span>
                  <span className="text-slate-500 font-mono">
                    Accuracy: {e.brier_model?.toFixed(3) ?? "—"}
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
// Match of the Day
// ---------------------------------------------------------------------------

function MatchOfTheDayCard({ match }: { match: Matchup }) {
  const { home, away, match_date } = match
  const dateStr = (() => {
    try {
      return new Date(match_date).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })
    } catch { return match_date }
  })()

  const homeProb = home.model_advance_prob
  const awayProb = away.model_advance_prob
  const favoured = (homeProb ?? 0) >= (awayProb ?? 0) ? home : away
  const favPct   = Math.round(Math.max(homeProb ?? 0, awayProb ?? 0) * 100)

  return (
    <SectionCard title="Next Match" subtitle={dateStr}>
      <div className="flex items-center gap-3">
        {/* Home */}
        <div className="flex-1 min-w-0 text-center">
          <div className="text-2xl">{flag(home.name)}</div>
          <p className="text-xs font-medium text-slate-200 mt-1 truncate">{home.name}</p>
          {homeProb != null && (
            <p className="text-[11px] font-mono text-emerald-400">{Math.round(homeProb * 100)}%</p>
          )}
        </div>

        <div className="shrink-0 text-center">
          <span className="text-xs text-slate-600 font-medium">vs</span>
        </div>

        {/* Away */}
        <div className="flex-1 min-w-0 text-center">
          <div className="text-2xl">{flag(away.name)}</div>
          <p className="text-xs font-medium text-slate-200 mt-1 truncate">{away.name}</p>
          {awayProb != null && (
            <p className="text-[11px] font-mono text-emerald-400">{Math.round(awayProb * 100)}%</p>
          )}
        </div>
      </div>

      {homeProb != null && (
        <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
          <div className="h-full bg-emerald-500 rounded-full" style={{ width: `${Math.round(homeProb * 100)}%` }} />
        </div>
      )}

      {favPct > 0 && (
        <p className="text-xs text-slate-500 text-center">
          {favoured.name} favoured at {favPct}%
        </p>
      )}

      <Link href="/matchups" className="text-xs text-emerald-500 hover:text-emerald-400 transition-colors">
        All matchups →
      </Link>
    </SectionCard>
  )
}

// ---------------------------------------------------------------------------
// Insight of the Day (biggest model vs market gap)
// ---------------------------------------------------------------------------

function InsightCard({ match }: { match: Matchup }) {
  const { home, away } = match
  const modelH  = home.model_advance_prob ?? 0
  const marketH = home.market_advance_prob ?? 0
  const delta   = modelH - marketH
  const absDelta = Math.abs(delta)

  const valueSide  = delta > 0 ? home : away
  const valueDelta = Math.round(absDelta * 100)
  const bookieSide = delta > 0 ? away : home

  return (
    <SectionCard
      title="Value Pick"
      subtitle="Biggest gap between our model and the bookies"
    >
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xl">{flag(valueSide.name)}</span>
          <div>
            <p className="text-sm font-semibold text-slate-100">{valueSide.name}</p>
            <p className="text-xs text-slate-500">
              vs {bookieSide.name}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/20"
          >
            +{valueDelta}% edge
          </span>
          <span className="text-xs text-slate-500">
            model {Math.round((delta > 0 ? modelH : 1 - modelH) * 100)}% · bookies {Math.round((delta > 0 ? marketH : 1 - marketH) * 100)}%
          </span>
        </div>

        <p className="text-xs text-slate-500 leading-relaxed">
          Our model gives {valueSide.name} a {valueDelta}-point edge over what the bookmakers currently imply.
        </p>
      </div>

      <Link href="/matchups" className="text-xs text-emerald-500 hover:text-emerald-400 transition-colors">
        See all matchups →
      </Link>
    </SectionCard>
  )
}

// ---------------------------------------------------------------------------
// Top Performers
// ---------------------------------------------------------------------------

function TopPerformersCard({ players }: { players: PlayerResponse[] }) {
  return (
    <SectionCard title="Top Performers" subtitle="Highest-rated players at this World Cup">
      {players.length === 0 ? (
        <p className="text-sm text-slate-500 italic">No player data available yet.</p>
      ) : (
        <motion.ol variants={container} initial="hidden" animate="show" className="space-y-2">
          {players.map((p, i) => (
            <motion.li key={p.reep_id} variants={row}>
              <Link
                href={`/players/${p.reep_id}`}
                className="flex items-center gap-3 py-1 rounded-lg hover:bg-slate-800 px-1 transition-colors group"
              >
                <span className="w-5 text-center text-xs font-bold text-slate-600 tabular-nums shrink-0">
                  {i + 1}
                </span>
                <span className="text-base shrink-0">{flag(p.national_team ?? p.nationality ?? "")}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-slate-200 truncate group-hover:text-emerald-400 transition-colors">
                    {p.name ?? p.reep_id}
                  </p>
                  <p className="text-xs text-slate-500 truncate">
                    {p.national_team ?? p.nationality} · {p.position_micro ?? p.position_macro}
                  </p>
                </div>
                <span className="text-sm font-bold text-emerald-400 tabular-nums shrink-0">
                  {p.posterior_mean.toFixed(2)}
                </span>
              </Link>
            </motion.li>
          ))}
        </motion.ol>
      )}

      <Link href="/players" className="text-xs text-emerald-500 hover:text-emerald-400 transition-colors">
        Search all players →
      </Link>
    </SectionCard>
  )
}

// ---------------------------------------------------------------------------
// Overnight Deltas
// ---------------------------------------------------------------------------

function OvernightDeltasCard({ overnight }: { overnight: InsightsOvernight[] }) {
  const sorted = overnight
    .slice()
    .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
    .slice(0, 6)

  return (
    <SectionCard
      title="Overnight Swings"
      subtitle="Biggest title-probability shifts since yesterday's run"
    >
      {sorted.length === 0 ? (
        <p className="text-sm text-slate-500 italic">No overnight delta data available.</p>
      ) : (
        <motion.ol variants={container} initial="hidden" animate="show" className="space-y-2.5">
          {sorted.map((item) => {
            const isUp   = item.delta >= 0
            const absDelta = Math.abs(item.delta * 100)
            const arrow  = isUp ? "▲" : "▼"
            const deltaColor = isUp ? "text-emerald-400" : "text-rose-400"
            const barColor   = isUp ? "bg-emerald-500" : "bg-rose-500"
            return (
              <motion.li key={item.team} variants={row} className="flex items-center gap-3">
                <span className={`text-xs font-bold w-3 shrink-0 ${deltaColor}`}>{arrow}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex justify-between items-baseline mb-1">
                    <span className="text-sm font-medium text-slate-200 truncate">
                      {flag(item.team)} {item.team}
                    </span>
                    <div className="flex items-baseline gap-1.5 shrink-0 ml-2">
                      <span className={`text-xs font-bold tabular-nums ${deltaColor}`}>
                        {isUp ? "+" : "−"}{absDelta.toFixed(1)}pp
                      </span>
                      <span className="text-xs font-mono text-slate-500">
                        {(item.title_prob * 100).toFixed(1)}%
                      </span>
                    </div>
                  </div>
                  <div className="h-1 bg-slate-800 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${barColor}`}
                      style={{ width: `${Math.min(absDelta * 10, 100).toFixed(0)}%` }}
                    />
                  </div>
                </div>
              </motion.li>
            )
          })}
        </motion.ol>
      )}
    </SectionCard>
  )
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

export default function HomeCards({
  champions,
  brierSummary,
  brierEntries,
  matchOfTheDay,
  insightMatch,
  topPlayers,
  overnight,
}: {
  champions: SimTeam[]
  brierSummary: BrierSummary
  brierEntries: BrierEntry[]
  matchOfTheDay: Matchup | null
  insightMatch: Matchup | null
  topPlayers: PlayerResponse[]
  overnight: InsightsOvernight[] | null
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
      {matchOfTheDay && <MatchOfTheDayCard match={matchOfTheDay} />}
      {insightMatch && <InsightCard match={insightMatch} />}
      {overnight && overnight.length > 0 && <OvernightDeltasCard overnight={overnight} />}
      <TopPerformersCard players={topPlayers} />
    </motion.div>
  )
}
