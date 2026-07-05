import type { Metadata } from "next"
import { getBrier } from "@/lib/server-data"
import SummaryCards from "./SummaryCards"
import MatchLogTable from "./MatchLogTable"
import CalibrationScatter from "./CalibrationScatter"
import ValuePickScoreboard from "./ValuePickScoreboard"

export const metadata: Metadata = {
  title: "Track Record",
  description: "Every WC 2026 knockout match graded — TrueScout model vs bookmaker odds vs actual result.",
  openGraph: {
    title: "Track Record · TrueScout WC 2026",
    description: "Every knockout match graded — model predictions vs bookmaker odds vs actual result.",
    type: "website",
  },
  twitter: { card: "summary_large_image" },
}

export default async function BrierPage() {
  const data = await getBrier().catch(() => null)

  const isEmpty = !data || data.summary.n_matches === 0

  return (
    <div className="max-w-6xl 2xl:max-w-7xl mx-auto space-y-6">

      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-100">Track Record</h1>
        <p className="mt-1 text-sm text-slate-500">
          Every completed knockout match graded — model predictions vs bookmaker odds vs actual result.
        </p>
      </div>

      {/* Empty state */}
      {isEmpty ? (
        <div className="py-28 flex flex-col items-center gap-4 text-center">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.2}
            className="w-12 h-12 text-slate-700"
          >
            <circle cx="12" cy="12" r="10" />
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 8v4l3 3"
            />
          </svg>
          <div className="space-y-2">
            <p className="text-slate-400 font-medium">Waiting for knockout results</p>
            <p className="text-slate-600 text-sm max-w-sm">
              The model will be graded against the market after each completed
              knockout match. Check back after Round of 32 concludes.
            </p>
          </div>
        </div>
      ) : (
        <>
          {/* Summary cards */}
          <SummaryCards s={data.summary} />

          {/* Two-column: scatter + table */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
            <CalibrationScatter entries={data.entries} />
            <div className="flex flex-col">
              <MatchLogTable entries={data.entries} />
            </div>
          </div>

          {/* Value pick track record */}
          <ValuePickScoreboard entries={data.entries} />
        </>
      )}

    </div>
  )
}
