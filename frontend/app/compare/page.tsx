import type { Metadata } from "next"
import { Suspense } from "react"
import { readFileSync } from "fs"
import path from "path"
import type { PlayerResponse } from "@/lib/api"
import CompareClient from "./CompareClient"

export const metadata: Metadata = {
  title: "Compare Players",
  description: "Side-by-side Bayesian rating and attribute breakdown for any two WC 2026 players.",
  openGraph: {
    title: "Compare Players · TrueScout WC 2026",
    description: "Side-by-side rating and attribute breakdown for any two WC 2026 players.",
    type: "website",
  },
  twitter: { card: "summary_large_image" },
}

function loadPlayers(): PlayerResponse[] {
  try {
    const filePath = path.join(process.cwd(), "public", "data", "players.json")
    return JSON.parse(readFileSync(filePath, "utf-8")) as PlayerResponse[]
  } catch {
    return []
  }
}

export default function ComparePage() {
  const allPlayers = loadPlayers()

  return (
    <div className="max-w-3xl lg:max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-100">Compare Players</h1>
        <p className="mt-1 text-sm text-slate-500">
          Side-by-side rating and attribute breakdown
        </p>
      </div>

      <Suspense fallback={null}>
        <CompareClient allPlayers={allPlayers} />
      </Suspense>
    </div>
  )
}
