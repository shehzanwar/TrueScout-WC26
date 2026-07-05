import type { Metadata } from "next"
import PlayerSearchClient from "./PlayerSearchClient"

export const metadata: Metadata = {
  title: "Player Search",
  description: "Search and compare Bayesian ratings for all 3,274 players at WC 2026.",
  openGraph: {
    title: "Player Search · TrueScout WC 2026",
    description: "Search and compare Bayesian ratings for all 3,274 players at WC 2026.",
    type: "website",
  },
  twitter: { card: "summary_large_image" },
}

export default async function PlayersPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>
}) {
  const sp = await searchParams
  const initialQ = typeof sp.q === "string" ? sp.q : ""

  return (
    <div className="max-w-3xl lg:max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-100">Player Search</h1>
        <p className="mt-1 text-sm text-slate-500">
          TrueScout ratings across 3,274 WC 2026 players · accent-insensitive
        </p>
      </div>

      <PlayerSearchClient initialQ={initialQ} />
    </div>
  )
}
