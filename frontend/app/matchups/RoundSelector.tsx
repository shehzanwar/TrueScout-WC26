import Link from "next/link"

const ROUNDS = [
  { code: "R32", label: "Round of 32" },
  { code: "R16", label: "Round of 16" },
  { code: "QF",  label: "Quarter-finals" },
  { code: "SF",  label: "Semi-finals" },
  { code: "3P",  label: "3rd Place" },
  { code: "F",   label: "Final" },
] as const

export default function RoundSelector({ activeRound }: { activeRound: string }) {
  return (
    <div className="flex flex-wrap gap-2">
      {ROUNDS.map(({ code, label }) => {
        const active = activeRound === code
        return (
          <Link
            key={code}
            href={`/matchups?round=${code}`}
            className={[
              "px-3.5 py-1.5 rounded-lg text-sm font-medium border transition-colors",
              active
                ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
                : "bg-slate-900 text-slate-400 border-slate-800 hover:border-slate-700 hover:text-slate-200",
            ].join(" ")}
          >
            {label}
          </Link>
        )
      })}
    </div>
  )
}
