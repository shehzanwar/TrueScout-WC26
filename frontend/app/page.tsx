import { getSimulations, getBrier } from "@/lib/api"
import HomeCards from "./components/HomeCards"

export default async function HomePage() {
  const [simData, brierData] = await Promise.all([
    getSimulations().catch(() => null),
    getBrier().catch(() => null),
  ])

  // Extract champions round (round === "W") for title favorites
  const championsRound = simData?.rounds.find((r) => r.round === "W")
  const champions = championsRound?.teams ?? simData?.rounds.at(-1)?.teams ?? []

  const brierSummary = brierData?.summary ?? {
    n_matches: 0,
    n_with_market: 0,
    avg_brier_model: null,
    avg_brier_market: null,
    avg_log_loss_model: null,
    avg_log_loss_market: null,
    coin_flip_brier: 0.25,
    coin_flip_log_loss: 1.0,
    brier_skill_vs_coin: null,
    brier_skill_vs_market: null,
  }

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-100">Dashboard</h1>
        <p className="mt-1 text-sm text-slate-500">
          {simData
            ? `${simData.n_iterations.toLocaleString()} simulations · run ${simData.run_date}`
            : "Live model output from the nightly batch"}
        </p>
      </div>

      <HomeCards
        champions={champions}
        brierSummary={brierSummary}
        brierEntries={brierData?.entries ?? []}
      />
    </div>
  )
}
