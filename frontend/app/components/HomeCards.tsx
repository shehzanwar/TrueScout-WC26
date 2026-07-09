"use client"

import Link from "next/link"
import { motion } from "framer-motion"
import { playerSlug, type SimTeam, type BrierSummary, type BrierEntry, type Matchup, type PlayerResponse, type InsightsOvernight, type BracketSlotEntry } from "@/lib/api"
import { FlagIcon } from "@/app/components/FlagIcon"
import Tooltip, { LabelWithInfo } from "@/app/components/Tooltip"

// ---------------------------------------------------------------------------
// Animation variants — minimal: one subtle lift per card only
// ---------------------------------------------------------------------------

const card = {
  hidden: { y: 10, opacity: 0 },
  show: { y: 0, opacity: 1, transition: { duration: 0.28, ease: "easeOut" as const } },
}

// ---------------------------------------------------------------------------
// Shared
// ---------------------------------------------------------------------------


function StatPill({ value, label, accent = false, tip }: { value: string; label: string; accent?: boolean; tip?: string }) {
  return (
    <div className="flex flex-col items-center gap-0.5">
      <span className={`text-lg font-bold tabular-nums ${accent ? "text-emerald-400" : "text-slate-100"}`}>
        {value}
      </span>
      <span className="text-xs text-slate-500 uppercase tracking-wide">
        {tip ? <LabelWithInfo label={label} tip={tip} /> : label}
      </span>
    </div>
  )
}

function SectionCard({
  title, subtitle, children, variant = "default",
}: {
  title: string; subtitle?: string; children: React.ReactNode; variant?: "default" | "inset" | "ruled"
}) {
  const wrapCls =
    variant === "inset"
      ? "bg-slate-800/30 border border-slate-800/60 rounded-xl p-5 flex flex-col gap-4"
      : variant === "ruled"
      ? "border-t border-slate-800 pt-5 flex flex-col gap-4"
      : "bg-slate-900 border border-slate-800 rounded-xl p-5 flex flex-col gap-4"
  return (
    <motion.div variants={card} className={wrapCls}>
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

const _DEFENDING_CHAMPION = "Argentina"
const _HOST_NATIONS = new Set(["United States", "Mexico", "Canada"])

function FavoritesCard({
  champions,
  overnight,
}: {
  champions: SimTeam[]
  overnight?: InsightsOvernight[] | null
}) {
  const top5 = champions.slice().sort((a, b) => b.title_prob - a.title_prob).slice(0, 5)
  const maxProb = top5[0]?.title_prob ?? 1
  // Use 2dp when toFixed(1) would produce duplicate labels among the top 5
  const allProbs = top5.map(t => t.title_prob)
  function fmtProb(p: number): string {
    const pct = p * 100
    const label1 = pct.toFixed(1)
    const collision = allProbs.some(q => q !== p && (q * 100).toFixed(1) === label1)
    return collision ? `${pct.toFixed(2)}%` : `${label1}%`
  }
  const risingTeams = new Set(
    (overnight ?? []).filter((o) => o.delta > 0.01).map((o) => o.team),
  )
  return (
    <SectionCard title="Title Favorites" subtitle="Chance of winning the World Cup">
      {top5.length === 0 ? (
        <p className="text-sm text-slate-500 italic">No simulation data yet.</p>
      ) : (
        <ol className="space-y-2.5">
          {top5.map((team, i) => (
            <li key={team.team_id} className="flex items-center gap-3">
              <span className="w-5 text-center text-xs font-bold text-slate-600 tabular-nums">{i + 1}</span>
              <div className="flex-1 min-w-0">
                <div className="flex justify-between items-center mb-1">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span className="text-sm font-medium text-slate-200 truncate">{team.team_id}</span>
                    {team.team_id === _DEFENDING_CHAMPION && (
                      <span className="shrink-0 inline-flex px-1.5 rounded-full text-[9px] font-medium bg-yellow-500/15 text-yellow-400 border border-yellow-500/20">
                        holders
                      </span>
                    )}
                    {_HOST_NATIONS.has(team.team_id) && (
                      <span className="shrink-0 inline-flex px-1.5 rounded-full text-[9px] font-medium bg-sky-500/15 text-sky-400 border border-sky-500/20">
                        hosts
                      </span>
                    )}
                    {risingTeams.has(team.team_id) && (
                      <span className="shrink-0 inline-flex px-1.5 rounded-full text-[9px] font-medium bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">
                        rising
                      </span>
                    )}
                  </div>
                  <span className="text-xs font-mono text-emerald-400 shrink-0 ml-2">
                    {fmtProb(team.title_prob)}
                  </span>
                </div>
                <div className="h-1 bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-emerald-500 rounded-full"
                    style={{ width: `${((team.title_prob / maxProb) * 100).toFixed(0)}%` }}
                  />
                </div>
              </div>
            </li>
          ))}
        </ol>
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
    <SectionCard title="Prediction Accuracy" subtitle="Did our model pick the winners?" variant="inset">
      {summary.n_matches === 0 ? (
        <p className="text-sm text-slate-500 italic">No completed knockout matches graded yet. Check back after the first round.</p>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-3 py-1">
            <StatPill value={String(summary.n_matches)} label="Graded" />
            <StatPill
              value={brierModel}
              label="Brier Score"
              accent
              tip="Measures how accurate our probability predictions were. 0.0 = perfect, 0.25 = random guessing, 1.0 = always wrong. Lower is better."
            />
            <StatPill
              value={skillPct}
              label="Skill Edge"
              accent={skillPos}
              tip="How much better (or worse) our model is versus a 50/50 coin flip. Positive means the model is outperforming random chance."
            />
          </div>
          <p className="text-[11px] text-slate-600 text-center pb-1">lower score = more accurate · 0.25 = coin flip</p>
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
              {[...entries].reverse().slice(0, 3).map((e) => (
                <div key={e.event_id} className="flex items-center justify-between text-xs">
                  <span className="text-slate-400">
                    {e.home_team} <span className="text-slate-600">vs</span> {e.away_team}
                  </span>
                  <span className="text-slate-500 font-mono">
                    Brier: {e.brier_model?.toFixed(3) ?? "—"}
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
      return new Date(match_date + "T12:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })
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
          <div className="flex justify-center"><FlagIcon name={home.name} size={28} /></div>
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
          <div className="flex justify-center"><FlagIcon name={away.name} size={28} /></div>
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

function InsightCard({ match }: { match: Matchup | null }) {
  if (!match) {
    return (
      <SectionCard title="Value Pick" subtitle="Biggest gap between our model and the bookies">
        <p className="text-sm text-slate-500 italic leading-relaxed">
          No strong value picks today — model and bookies are in alignment.
        </p>
        <Link href="/matchups" className="text-xs text-emerald-500 hover:text-emerald-400 transition-colors">
          See all matchups →
        </Link>
      </SectionCard>
    )
  }

  const { home, away } = match
  const modelH   = home.model_advance_prob ?? 0
  const marketH  = home.market_advance_prob ?? 0
  const delta    = modelH - marketH
  const absDelta = Math.abs(delta)

  const valueSide  = delta > 0 ? home : away
  const bookieSide = delta > 0 ? away : home
  const valueDelta = Math.round(absDelta * 100)
  const modelProb  = delta > 0 ? modelH  : 1 - modelH
  const bookiesProb = delta > 0 ? marketH : 1 - marketH

  // High-variance call: edge > 20pp AND model gives >2× the bookies' implied probability
  const isHighVariance = valueDelta > 20 && modelProb > 2 * bookiesProb

  return (
    <SectionCard
      title="Value Pick"
      subtitle="Biggest gap between our model and the bookies"
    >
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <FlagIcon name={valueSide.name} size={20} />
          <div>
            <p className="text-sm font-semibold text-slate-100">{valueSide.name}</p>
            <p className="text-xs text-slate-500">vs {bookieSide.name}</p>
          </div>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">
            +{valueDelta}% edge
          </span>
          <span className="text-xs text-slate-500">
            model {Math.round(modelProb * 100)}% · bookies {Math.round(bookiesProb * 100)}%
          </span>
          {isHighVariance && (
            <Tooltip content="This is a large disagreement between our model and the bookies. These calls have higher variance — the model sees something the market doesn't, but it could go either way.">
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-500/15 text-amber-400 border border-amber-500/25 cursor-default select-none">
                <svg viewBox="0 0 16 16" fill="currentColor" className="w-3 h-3 shrink-0">
                  <path d="M6.457 1.047c.659-1.234 2.427-1.234 3.086 0l6.082 11.378A1.75 1.75 0 0 1 14.082 15H1.918a1.75 1.75 0 0 1-1.543-2.575Zm1.763.707a.25.25 0 0 0-.44 0L1.698 13.132a.25.25 0 0 0 .22.368h12.164a.25.25 0 0 0 .22-.368Zm.53 3.996v2.5a.75.75 0 0 1-1.5 0v-2.5a.75.75 0 0 1 1.5 0ZM9 11a1 1 0 1 1-2 0 1 1 0 0 1 2 0Z" />
                </svg>
                high-variance call
              </span>
            </Tooltip>
          )}
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
    <SectionCard title="Top Performers" subtitle="Highest-rated players at this World Cup" variant="inset">
      {players.length === 0 ? (
        <p className="text-sm text-slate-500 italic">No player data available yet.</p>
      ) : (
        <ol className="space-y-2">
          {players.map((p, i) => (
            <li key={p.reep_id}>
              <Link
                href={`/players/${playerSlug(p)}`}
                className="flex items-center gap-3 py-1 rounded-lg hover:bg-slate-800 px-1 transition-colors group"
              >
                <span className="w-5 text-center text-xs font-bold text-slate-600 tabular-nums shrink-0">
                  {i + 1}
                </span>
                <span className="shrink-0"><FlagIcon name={p.national_team ?? p.nationality ?? ""} size={16} /></span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-slate-200 truncate group-hover:text-emerald-400 transition-colors">
                    {p.name ?? p.reep_id}
                  </p>
                  <p className="text-xs text-slate-500 truncate">
                    {p.national_team ?? p.nationality} · {p.position_micro ?? p.position_macro}
                    {p.age_at_wc != null ? ` · ${p.age_at_wc}y` : ""}
                  </p>
                </div>
                <span className="text-sm font-semibold text-slate-300 tabular-nums shrink-0">
                  {p.posterior_mean.toFixed(2)}
                </span>
              </Link>
            </li>
          ))}
        </ol>
      )}

      <Link href="/players" className="text-xs text-slate-500 hover:text-slate-300 transition-colors">
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
        <ol className="space-y-2.5">
          {sorted.map((item) => {
            const isUp   = item.delta >= 0
            const absDelta = Math.abs(item.delta * 100)
            const arrow  = isUp ? "▲" : "▼"
            const deltaColor = isUp ? "text-emerald-400" : "text-rose-400"
            const barColor   = isUp ? "bg-emerald-500" : "bg-rose-500"
            return (
              <li key={item.team} className="flex items-center gap-3">
                <span className={`text-xs font-bold w-3 shrink-0 ${deltaColor}`}>{arrow}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex justify-between items-baseline mb-1">
                    <span className="text-sm font-medium text-slate-200 truncate">
                      <FlagIcon name={item.team} size={16} /> {item.team}
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
              </li>
            )
          })}
        </ol>
      )}
    </SectionCard>
  )
}

// ---------------------------------------------------------------------------
// Tournament Stats (scorers / assists / defensive actions)
// ---------------------------------------------------------------------------

interface TopStatEntry {
  reep_id: string
  slug: string
  name: string
  national_team: string
  value: number
  detail?: string
  wc_minutes: number
}

export interface TournamentStats {
  top_scorers: TopStatEntry[]
  top_assists: TopStatEntry[]
  top_defensive: TopStatEntry[]
}

function StatsColumn({
  title, entries, unit, accent,
}: {
  title: string
  entries: TopStatEntry[]
  unit: string
  accent: string
}) {
  if (!entries.length) return null
  return (
    <div className="flex flex-col gap-2.5 min-w-0">
      <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">{title}</p>
      <ol className="space-y-1">
        {entries.map((p, i) => (
          <li key={p.reep_id}>
            <Link
              href={`/players/${p.slug}`}
              className="flex items-center gap-2 py-0.5 px-1 rounded hover:bg-slate-800/60 transition-colors group"
            >
              <span className="w-4 text-center text-[10px] font-bold text-slate-600 tabular-nums shrink-0">
                {i + 1}
              </span>
              <span className="shrink-0">
                <FlagIcon name={p.national_team} size={13} />
              </span>
              <span className="flex-1 min-w-0 text-xs text-slate-200 truncate group-hover:text-sky-400 transition-colors">
                {p.name}
              </span>
              <span className={`text-xs font-bold tabular-nums shrink-0 ${accent}`}>
                {p.value}{unit}
              </span>
            </Link>
            {p.detail && (
              <p className="text-[10px] text-slate-600 pl-7 -mt-0.5 leading-none">
                {p.detail}
              </p>
            )}
          </li>
        ))}
      </ol>
    </div>
  )
}

function TournamentStatsCard({ stats }: { stats: TournamentStats }) {
  return (
    <motion.div
      variants={card}
      className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-xl p-5 flex flex-col gap-4"
    >
      <div>
        <h2 className="text-sm font-semibold text-slate-100 uppercase tracking-wider">
          Tournament Leaders
        </h2>
        <p className="text-xs text-slate-500 mt-0.5">
          Goals · Assists · Defensive actions (tackles + interceptions) across all matches
        </p>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 divide-y sm:divide-y-0 sm:divide-x divide-slate-800/60 gap-y-5 sm:gap-y-0">
        <div className="sm:pr-5">
          <StatsColumn title="Top Scorers" entries={stats.top_scorers} unit="G" accent="text-amber-400" />
        </div>
        <div className="sm:px-5 pt-5 sm:pt-0">
          <StatsColumn title="Top Assisters" entries={stats.top_assists} unit="A" accent="text-sky-400" />
        </div>
        <div className="sm:pl-5 pt-5 sm:pt-0">
          <StatsColumn title="Defensive Actions" entries={stats.top_defensive} unit="" accent="text-emerald-400" />
        </div>
      </div>
    </motion.div>
  )
}

// ---------------------------------------------------------------------------
// Bracket Outlook (3rd column at 2xl+)
// ---------------------------------------------------------------------------

const BRACKET_ROUND_ORDER = ["R32", "R16", "QF", "SF", "F"] as const
const BRACKET_ROUND_LABELS: Record<string, string> = {
  R32: "Round of 32",
  R16: "Round of 16",
  QF:  "Quarterfinals",
  SF:  "Semifinals",
  F:   "Final",
}

function BracketPreviewCard({ slots }: { slots: BracketSlotEntry[] }) {
  const currentRound = BRACKET_ROUND_ORDER.find((r) =>
    slots.some((s) => s.round === r && s.top.prob < 1.0)
  ) ?? null

  if (!currentRound) return null

  const currentSlots = slots
    .filter((s) => s.round === currentRound)
    .sort((a, b) => a.slot_idx - b.slot_idx)

  return (
    <SectionCard
      title="Bracket Outlook"
      subtitle={`${BRACKET_ROUND_LABELS[currentRound] ?? currentRound} · top pick per slot`}
    >
      <ol className="space-y-1.5">
        {currentSlots.map((slot) => {
          const confirmed = slot.top.prob >= 1.0
          return (
            <li key={slot.slot_idx} className="flex items-center gap-2">
              <span className="w-4 text-right text-[10px] font-mono text-slate-600 tabular-nums shrink-0">
                {slot.slot_idx + 1}
              </span>
              <span className="shrink-0">
                <FlagIcon name={slot.top.team} size={14} />
              </span>
              <span
                className={`flex-1 min-w-0 text-xs truncate ${
                  confirmed ? "text-slate-500" : "text-slate-200"
                }`}
              >
                {slot.top.team}
              </span>
              {confirmed ? (
                <span className="text-[10px] text-emerald-600 shrink-0">✓</span>
              ) : (
                <span className="text-[10px] font-mono text-emerald-400 tabular-nums shrink-0">
                  {Math.round(slot.top.prob * 100)}%
                </span>
              )}
            </li>
          )
        })}
      </ol>
      <Link href="/bracket" className="text-xs text-emerald-500 hover:text-emerald-400 transition-colors">
        Full bracket →
      </Link>
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
  bracketSlots = [],
  tournamentStats = null,
}: {
  champions: SimTeam[]
  brierSummary: BrierSummary
  brierEntries: BrierEntry[]
  matchOfTheDay: Matchup | null
  insightMatch: Matchup | null
  topPlayers: PlayerResponse[]
  overnight: InsightsOvernight[] | null
  bracketSlots?: BracketSlotEntry[]
  tournamentStats?: TournamentStats | null
}) {
  return (
    <div className="2xl:flex 2xl:gap-5 2xl:items-start">
      {/* Main 2-col grid */}
      <div className="flex-1 min-w-0 grid grid-cols-1 lg:grid-cols-2 gap-5">
        <FavoritesCard champions={champions} overnight={overnight} />
        <CalibrationCard summary={brierSummary} entries={brierEntries} />
        {matchOfTheDay && <MatchOfTheDayCard match={matchOfTheDay} />}
        <InsightCard match={insightMatch} />
        {overnight && overnight.length > 0 && <OvernightDeltasCard overnight={overnight} />}
        <TopPerformersCard players={topPlayers} />
        {tournamentStats && <TournamentStatsCard stats={tournamentStats} />}
      </div>
      {/* 3rd column: bracket preview at 2xl+ */}
      {bracketSlots.length > 0 && (
        <div className="hidden 2xl:block 2xl:w-64 2xl:shrink-0">
          <BracketPreviewCard slots={bracketSlots} />
        </div>
      )}
    </div>
  )
}
