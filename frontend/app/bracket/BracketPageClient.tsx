"use client"

import { useEffect, useState } from "react"
import type { SimulationsResponse, MatchupsResponse } from "@/lib/api"
import { buildBracket } from "@/lib/bracket"
import type { BracketData } from "@/lib/bracket"
import BracketGrid from "./BracketGrid"

export default function BracketPageClient() {
  const [bracket, setBracket] = useState<BracketData | null>(null)
  const [runInfo, setRunInfo] = useState<{ date: string; n: number } | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const [simRes, matchupsRes] = await Promise.all([
          fetch("/data/simulations.json"),
          fetch("/data/matchups.json"),
        ])
        if (!simRes.ok || !matchupsRes.ok) throw new Error("fetch failed")
        const simData: SimulationsResponse = await simRes.json()
        const allMatchups: Record<string, MatchupsResponse> = await matchupsRes.json()

        if (cancelled) return
        setRunInfo({ date: simData.run_date, n: simData.n_iterations })

        const r32Data = allMatchups["R32"] ?? null
        const r16Data = allMatchups["R16"] ?? undefined
        if (!r32Data) { setError(true); return }

        setBracket(buildBracket(simData, r32Data, r16Data))
      } catch {
        if (!cancelled) setError(true)
      }
    }

    load()
    return () => { cancelled = true }
  }, [])

  if (error) {
    return (
      <div className="py-24 flex flex-col items-center gap-3 text-center">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className="w-10 h-10 text-slate-700">
          <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 3v11.25A2.25 2.25 0 0 0 6 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0 1 18 16.5h-2.25m-7.5 0h7.5m-7.5 0-1 3m8.5-3 1 3m0 0 .5 1.5m-.5-1.5h-9.5m0 0-.5 1.5m.75-9 3-3 2.148 2.148A12.061 12.061 0 0 1 16.5 7.605" />
        </svg>
        <p className="text-slate-500 text-sm">Bracket data not available.</p>
        <p className="text-slate-700 text-xs">Run the nightly pipeline to generate simulation results.</p>
      </div>
    )
  }

  if (!bracket) {
    return (
      <>
        <p className="text-sm text-slate-600 animate-pulse -mt-3">Loading bracket…</p>
        <div className="py-24" />
      </>
    )
  }

  return (
    <>
      {runInfo && (
        <p className="text-sm text-slate-500 -mt-3">
          {runInfo.n.toLocaleString()} Monte Carlo simulations · run {runInfo.date}
        </p>
      )}
      <BracketGrid bracket={bracket} />
    </>
  )
}
