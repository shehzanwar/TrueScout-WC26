import type { Metadata } from "next"
import { notFound } from "next/navigation"
import Link from "next/link"
import { getNationDetail, getNationSlugs } from "@/lib/server-data"
import type { NationDetail, NationMatch } from "@/lib/server-data"
import type { PlayerResponse } from "@/lib/api"
import { playerSlug } from "@/lib/api"
import { FlagIcon } from "@/app/components/FlagIcon"
import { ISO_CODES } from "@/lib/flags"
import FifaBadge from "@/app/players/FifaBadge"

// ---------------------------------------------------------------------------
// Static params — one route per R32 nation
// ---------------------------------------------------------------------------

export async function generateStaticParams() {
  const slugs = await getNationSlugs()
  return slugs.map((slug) => ({ slug }))
}

// ---------------------------------------------------------------------------
// Metadata
// ---------------------------------------------------------------------------

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>
}): Promise<Metadata> {
  const { slug } = await params
  const nation = await getNationDetail(slug).catch(() => null)
  if (!nation) return { title: "Nation not found" }

  const pct = (nation.title_prob * 100).toFixed(1)
  const status = nation.eliminated ? `Eliminated in ${ROUND_LABELS[nation.current_round] ?? nation.current_round}` : `${pct}% title chance`

  return {
    title: nation.name,
    description: `${nation.name} at WC 2026 · ${status} · ${nation.squad.length} players tracked`,
    openGraph: {
      title: `${nation.name} · TrueScout WC 2026`,
      description: `${status} — squad ratings, match history, and bracket analysis`,
    },
  }
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ROUND_LABELS: Record<string, string> = {
  R32: "Round of 32",
  R16: "Round of 16",
  QF:  "Quarterfinals",
  SF:  "Semifinals",
  F:   "Final",
}

const ROUND_ORDER = ["R32", "R16", "QF", "SF", "F"]

const POSITION_ORDER = ["GK", "DEF", "MID", "FWD"] as const
const POSITION_LABEL: Record<string, string> = {
  GK: "Goalkeepers", DEF: "Defenders", MID: "Midfielders", FWD: "Forwards",
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function matchResult(m: NationMatch, teamName: string): "W" | "L" | "D" | null {
  if (!m.completed) return null
  if (m.winner) return m.winner === teamName ? "W" : "L"
  if (m.teamScore == null || m.oppScore == null) return null
  if (m.teamScore > m.oppScore) return "W"
  if (m.teamScore < m.oppScore) return "L"
  return "D"
}

function resultLabel(res: "W" | "L" | "D" | null): { text: string; cls: string } {
  if (res === "W") return { text: "W", cls: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20" }
  if (res === "L") return { text: "L", cls: "text-rose-400 bg-rose-500/10 border-rose-500/20" }
  if (res === "D") return { text: "D", cls: "text-amber-400 bg-amber-500/10 border-amber-500/20" }
  return { text: "—", cls: "text-slate-600 bg-slate-800/50 border-slate-700" }
}

function fmtDate(iso: string): string {
  const [y, m, d] = iso.split("T")[0].split("-").map(Number)
  return new Date(y, m - 1, d).toLocaleDateString("en-US", { month: "short", day: "numeric" })
}

function teamOutlook(nation: NationDetail): string {
  const { name, title_prob, eliminated, current_round, matches } = nation
  const pct = title_prob >= 0.005
    ? `${Math.round(title_prob * 100)}%`
    : `${(title_prob * 100).toFixed(1)}%`
  const wins = matches.filter((m) => matchResult(m, name) === "W").length
  const roundLabel = ROUND_LABELS[current_round] ?? current_round

  if (eliminated) {
    return `${name} reached the ${roundLabel}, winning ${wins} match${wins !== 1 ? "es" : ""} before their campaign ended. The model's squad ratings reflect a genuinely competitive side — exits at this stage often come down to small margins rather than large quality gaps.`
  }
  if (title_prob >= 0.20) {
    return `At ${pct}, ${name} are the clearest favourite remaining in the draw. The model's confidence reflects squad depth that holds up across multiple positions. Anything short of a final would mark a significant underperformance relative to these pre-match signals.`
  }
  if (title_prob >= 0.10) {
    return `${name} sit at ${pct} — legitimate contenders, not just hopefuls. Their squad Bayesian ratings are among the strongest still in the tournament, and the simulation repeatedly finds paths to the final. The gap to the front-runner is real but not insurmountable.`
  }
  if (title_prob >= 0.05) {
    return `At ${pct}, ${name} are classic dark-horse material. The model's uncertainty here is substantial — a couple of results breaking their way could shift them dramatically up this table. Their key players' ratings suggest they're capable of hurting anyone on their day.`
  }
  return `${name} carry a ${pct} title chance — the model respects them enough to have advanced this far but sees a steep hill ahead. Knockout football rewards tactical discipline and tournament momentum, and this side has shown both.`
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function Chevron() {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" className="w-3 h-3 text-slate-700 shrink-0">
      <path fillRule="evenodd" d="M6.22 4.22a.75.75 0 0 1 1.06 0l3.25 3.25a.75.75 0 0 1 0 1.06l-3.25 3.25a.75.75 0 0 1-1.06-1.06L8.94 8 6.22 5.28a.75.75 0 0 1 0-1.06Z" clipRule="evenodd" />
    </svg>
  )
}

function MatchPill({ match, teamName }: { match: NationMatch; teamName: string }) {
  const res = matchResult(match, teamName)
  const { text, cls } = resultLabel(res)
  const score = match.completed && match.teamScore != null
    ? `${match.teamScore}–${match.oppScore}`
    : null

  return (
    <div className="flex items-center gap-3 py-2.5 border-b border-slate-800/60 last:border-0">
      <span className={`text-[10px] font-bold w-5 h-5 flex items-center justify-center rounded border ${cls} shrink-0 tabular-nums`}>
        {text}
      </span>
      <span className="text-[10px] text-slate-600 uppercase tracking-wider shrink-0 w-6">
        {match.round}
      </span>
      <div className="flex items-center gap-1.5 flex-1 min-w-0">
        <FlagIcon name={match.opponent} size={14} />
        <span className="text-sm text-slate-300 truncate">{match.opponent}</span>
      </div>
      {score && (
        <span className="text-sm font-mono font-semibold text-slate-100 tabular-nums shrink-0">
          {score}
        </span>
      )}
      {!match.completed && (
        <span className="text-xs text-slate-500 shrink-0">{fmtDate(match.match_date)}</span>
      )}
    </div>
  )
}

function SquadSection({ players, teamName }: { players: PlayerResponse[]; teamName: string }) {
  const byBucket = POSITION_ORDER.reduce(
    (acc, pos) => {
      acc[pos] = players.filter((p) => p.position_bucket === pos)
      return acc
    },
    {} as Record<string, PlayerResponse[]>,
  )

  return (
    <div className="space-y-6">
      {POSITION_ORDER.map((pos) => {
        const group = byBucket[pos]
        if (!group.length) return null
        return (
          <div key={pos}>
            <h3 className="text-[10px] font-semibold uppercase tracking-widest text-slate-600 mb-2 pb-1.5 border-b border-slate-800/60">
              {POSITION_LABEL[pos]} · {group.length}
            </h3>
            <div className="space-y-0.5">
              {group.map((p) => (
                <Link
                  key={p.reep_id}
                  href={`/players/${playerSlug(p)}`}
                  className="flex items-center gap-3 py-1.5 px-1 -mx-1 rounded-lg hover:bg-slate-800/40 transition-colors group"
                >
                  <div className="flex-1 min-w-0">
                    <span className="text-sm text-slate-300 group-hover:text-white transition-colors truncate block">
                      {p.name}
                    </span>
                    <span className="text-[10px] text-slate-600">
                      {p.position_micro ?? p.position_macro}
                      {p.wc_minutes ? ` · ${p.wc_minutes}′` : ""}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {p.fifa && <FifaBadge fifa={p.fifa} size="sm" />}
                    <span className="text-xs font-semibold text-slate-400 tabular-nums w-8 text-right">
                      {p.posterior_mean.toFixed(2)}
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default async function NationPage({
  params,
}: {
  params: Promise<{ slug: string }>
}) {
  const { slug } = await params
  const nation = await getNationDetail(slug).catch(() => null)
  if (!nation) notFound()

  const { name, title_prob, eliminated, current_round, matches, squad } = nation
  const iso = ISO_CODES[name]
  const flagBgUrl = iso ? `https://flagcdn.com/w640/${iso}.png` : null
  const wins = matches.filter((m) => matchResult(m, name) === "W").length
  const outlook = teamOutlook(nation)

  // Title prob display
  const titlePctStr = title_prob >= 0.005
    ? `${(title_prob * 100).toFixed(1)}%`
    : `${(title_prob * 100).toFixed(2)}%`

  // Sort matches in bracket order
  const sortedMatches = [...matches].sort(
    (a, b) => ROUND_ORDER.indexOf(a.round) - ROUND_ORDER.indexOf(b.round),
  )

  return (
    <div className="max-w-3xl mx-auto">

      {/* ── Breadcrumb ─────────────────────────────────────────────── */}
      <nav className="flex items-center gap-1.5 text-xs mb-6">
        <Link href="/nations" className="text-slate-500 hover:text-slate-300 transition-colors">
          Nations
        </Link>
        <Chevron />
        <span className="text-slate-300">{name}</span>
      </nav>

      {/* ── Hero ────────────────────────────────────────────────────── */}
      <div className="relative rounded-2xl overflow-hidden mb-8">
        {/* Flag image background at low opacity */}
        {flagBgUrl && (
          <div
            className="absolute inset-0"
            style={{
              backgroundImage: `url(${flagBgUrl})`,
              backgroundSize: "cover",
              backgroundPosition: "center",
              opacity: 0.06,
            }}
          />
        )}
        <div className="absolute inset-0 bg-gradient-to-r from-slate-900 via-slate-900/95 to-slate-900/80" />

        <div className="relative px-6 py-8 flex items-start justify-between gap-6">
          {/* Left: flag + name + status */}
          <div className="flex items-start gap-5">
            <div className="shrink-0 mt-1">
              <FlagIcon name={name} size={56} />
            </div>
            <div>
              <h1 className="text-4xl font-black tracking-tight text-white leading-none mb-2">
                {name}
              </h1>
              <div className="flex items-center gap-2 flex-wrap">
                {eliminated ? (
                  <span className="text-xs px-2.5 py-0.5 rounded-full bg-slate-700 text-slate-400 border border-slate-600">
                    Eliminated · {ROUND_LABELS[current_round] ?? current_round}
                  </span>
                ) : (
                  <span className="text-xs px-2.5 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                    {ROUND_LABELS[current_round] ?? current_round}
                  </span>
                )}
                <span className="text-xs text-slate-600">
                  {wins} win{wins !== 1 ? "s" : ""} · {squad.length} players tracked
                </span>
              </div>
            </div>
          </div>

          {/* Right: title probability — the one big number */}
          <div className="text-right shrink-0">
            <div className={`text-5xl font-black tabular-nums leading-none ${eliminated ? "text-slate-500" : "text-emerald-400"}`}>
              {eliminated ? "—" : titlePctStr}
            </div>
            <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-600 mt-1">
              {eliminated ? "eliminated" : "to win"}
            </div>
          </div>
        </div>
      </div>

      {/* ── Outlook ─────────────────────────────────────────────────── */}
      <div className="mb-8 pl-4 border-l-2 border-slate-700">
        <p className="text-sm text-slate-400 leading-relaxed">{outlook}</p>
      </div>

      {/* ── Two-column content ──────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_2fr] gap-8">

        {/* Left: match results */}
        <div>
          <h2 className="text-[10px] font-semibold uppercase tracking-widest text-slate-600 mb-3 pb-1.5 border-b border-slate-800">
            Knockout Path
          </h2>
          {sortedMatches.length === 0 ? (
            <p className="text-xs text-slate-600 italic">No matches recorded</p>
          ) : (
            <div>
              {sortedMatches.map((m) => (
                <MatchPill key={m.event_id} match={m} teamName={name} />
              ))}
            </div>
          )}

          {/* Model probability trace */}
          {nation.sim_rounds.length > 0 && !eliminated && (
            <div className="mt-6">
              <h2 className="text-[10px] font-semibold uppercase tracking-widest text-slate-600 mb-3 pb-1.5 border-b border-slate-800">
                Advance probability
              </h2>
              <div className="space-y-2">
                {nation.sim_rounds
                  .filter((r) => r.round !== "W")
                  .map((r) => (
                    <div key={r.round} className="flex items-center gap-3">
                      <span className="text-[10px] text-slate-600 uppercase tracking-wider w-6 shrink-0">
                        {r.round}
                      </span>
                      <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-emerald-500/60 rounded-full"
                          style={{ width: `${Math.round(r.advance_prob * 100)}%` }}
                        />
                      </div>
                      <span className="text-xs text-slate-400 tabular-nums shrink-0 w-9 text-right">
                        {Math.round(r.advance_prob * 100)}%
                      </span>
                    </div>
                  ))}
              </div>
            </div>
          )}
        </div>

        {/* Right: squad */}
        <div>
          <h2 className="text-[10px] font-semibold uppercase tracking-widest text-slate-600 mb-3 pb-1.5 border-b border-slate-800">
            Squad · {squad.length} players
          </h2>
          {squad.length === 0 ? (
            <p className="text-xs text-slate-600 italic">No player data available</p>
          ) : (
            <SquadSection players={squad} teamName={name} />
          )}
        </div>

      </div>
    </div>
  )
}
