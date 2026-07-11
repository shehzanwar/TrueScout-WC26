import type { Metadata } from "next"
import BracketPageClient from "./BracketPageClient"

export const metadata: Metadata = {
  title: "Bracket",
  description: "Monte Carlo knockout bracket for WC 2026 — R16 to Final win probabilities from 100k simulations.",
  openGraph: {
    title: "Knockout Tree · TrueScout WC 2026",
    description: "Monte Carlo knockout bracket — R16 to Final win probabilities from 100k simulations.",
    type: "website",
  },
  twitter: { card: "summary_large_image" },
}

export default function BracketPage() {
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-slate-100">Knockout Tree</h1>
      </div>
      <BracketPageClient />
    </div>
  )
}
