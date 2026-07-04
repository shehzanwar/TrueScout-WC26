import type { Metadata } from "next"
import { getSimulations, getMatchups } from "@/lib/server-data"
import { buildBracket } from "@/lib/bracket"
import BracketGrid from "./BracketGrid"

export const metadata: Metadata = { title: "Bracket" }

export default async function BracketPage() {
  const [simData, r32Data, r16Data] = await Promise.all([
    getSimulations().catch(() => null),
    getMatchups("R32").catch(() => null),
    getMatchups("R16").catch(() => null),
  ])

  const bracket = simData && r32Data
    ? buildBracket(simData, r32Data, r16Data ?? undefined)
    : null

  return (
    <div className="space-y-5">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-100">Knockout Tree</h1>
        <p className="mt-1 text-sm text-slate-500">
          {simData
            ? `${simData.n_iterations.toLocaleString()} Monte Carlo simulations · run ${simData.run_date}`
            : "R32 confirmed fixtures · R16–Final projected by Monte Carlo"}
        </p>
      </div>

      {/* Bracket or empty state */}
      {bracket ? (
        <BracketGrid bracket={bracket} />
      ) : (
        <div className="py-24 flex flex-col items-center gap-3 text-center">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.5}
            className="w-10 h-10 text-slate-700"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M3.75 3v11.25A2.25 2.25 0 0 0 6 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0 1 18 16.5h-2.25m-7.5 0h7.5m-7.5 0-1 3m8.5-3 1 3m0 0 .5 1.5m-.5-1.5h-9.5m0 0-.5 1.5m.75-9 3-3 2.148 2.148A12.061 12.061 0 0 1 16.5 7.605"
            />
          </svg>
          <p className="text-slate-500 text-sm">Bracket data not available.</p>
          <p className="text-slate-700 text-xs">
            Run the nightly pipeline to generate simulation results.
          </p>
        </div>
      )}
    </div>
  )
}
