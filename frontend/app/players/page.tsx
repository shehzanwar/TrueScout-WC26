import PlayerSearchClient from "./PlayerSearchClient"

export default async function PlayersPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>
}) {
  const sp = await searchParams
  const initialQ = typeof sp.q === "string" ? sp.q : ""

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-100">Player Search</h1>
        <p className="mt-1 text-sm text-slate-500">
          Bayesian posterior ratings across 3,274 WC 2026 players
        </p>
      </div>

      <PlayerSearchClient initialQ={initialQ} />
    </div>
  )
}
