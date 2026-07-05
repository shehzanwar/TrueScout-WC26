import type { Metadata } from "next"
import Link from "next/link"
import { getAllNations } from "@/lib/server-data"
import { FlagIcon } from "@/app/components/FlagIcon"

export const metadata: Metadata = {
  title: "Nations",
  description: "All 32 teams in the 2026 World Cup knockout stage — title probabilities and squad intelligence.",
}

const ROUND_LABELS: Record<string, string> = {
  R32: "Round of 32",
  R16: "Round of 16",
  QF:  "Quarterfinals",
  SF:  "Semifinals",
  F:   "Final",
}

export default async function NationsPage() {
  const nations = await getAllNations()

  const active      = nations.filter((n) => !n.eliminated).sort((a, b) => b.title_prob - a.title_prob)
  const eliminated  = nations.filter((n) =>  n.eliminated).sort((a, b) => a.name.localeCompare(b.name))

  return (
    <div className="max-w-3xl mx-auto">

      <div className="mb-8">
        <h1 className="text-2xl font-bold text-slate-100">Nations</h1>
        <p className="mt-1 text-sm text-slate-500">
          32 teams · Round of 32 onwards · sorted by title probability
        </p>
      </div>

      {/* ── Still in tournament ──────────────────────────────────────── */}
      <section>
        <div className="flex items-center gap-3 mb-3">
          <span className="w-2 h-2 rounded-full bg-emerald-400 shrink-0" />
          <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400">
            Still in the tournament — {active.length} teams
          </h2>
        </div>

        <div className="divide-y divide-slate-800/60">
          {active.map((n, i) => (
            <Link
              key={n.slug}
              href={`/nations/${n.slug}`}
              className="flex items-center gap-4 py-3 px-2 -mx-2 rounded-lg hover:bg-slate-800/40 transition-colors group"
            >
              <span className="w-6 text-right text-xs text-slate-600 tabular-nums shrink-0 font-mono">
                {i + 1}
              </span>
              <FlagIcon name={n.name} size={22} />
              <span className="flex-1 text-sm font-medium text-slate-200 group-hover:text-white transition-colors">
                {n.name}
              </span>
              <span className="text-[10px] text-slate-500 hidden sm:block shrink-0">
                {ROUND_LABELS[n.current_round] ?? n.current_round}
              </span>
              <span className="text-base font-bold text-emerald-400 tabular-nums shrink-0 w-14 text-right">
                {(n.title_prob * 100).toFixed(1)}%
              </span>
            </Link>
          ))}
        </div>
      </section>

      {/* ── Divider ─────────────────────────────────────────────────── */}
      <div className="my-8 border-t border-slate-800" />

      {/* ── Eliminated ──────────────────────────────────────────────── */}
      {(() => {
        const ELIM_ORDER = ["SF", "QF", "R16", "R32"] as const
        const buckets = ELIM_ORDER.map((round) => ({
          round,
          label: ROUND_LABELS[round] ?? round,
          teams: eliminated.filter((n) => n.current_round === round),
        })).filter((b) => b.teams.length > 0)

        return (
          <section className="space-y-6">
            {buckets.map((b) => (
              <div key={b.round}>
                <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-600 mb-3">
                  Eliminated in {b.label} — {b.teams.length} {b.teams.length === 1 ? "team" : "teams"}
                </h2>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-px bg-slate-800/40 rounded-xl overflow-hidden">
                  {b.teams.map((n) => (
                    <Link
                      key={n.slug}
                      href={`/nations/${n.slug}`}
                      className="flex items-center gap-2.5 px-4 py-3 bg-slate-950 hover:bg-slate-800/50 transition-colors group"
                    >
                      <FlagIcon name={n.name} size={18} />
                      <span className="text-sm text-slate-400 group-hover:text-slate-200 transition-colors truncate">
                        {n.name}
                      </span>
                    </Link>
                  ))}
                </div>
              </div>
            ))}
          </section>
        )
      })()}

    </div>
  )
}
