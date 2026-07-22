import { FlagIcon } from "./FlagIcon"

export default function TournamentArchiveBanner() {
  return (
    <div className="w-full shrink-0 bg-amber-950/70 border-b border-amber-800/30 px-4 py-2 flex items-center justify-center gap-2.5 flex-wrap">
      <span className="text-amber-400 font-bold text-xs tracking-wide">🏆 Spain</span>
      <span className="text-amber-800/80 text-xs">·</span>
      <span className="text-amber-200/70 text-xs font-medium">WC 2026 Champions</span>
      <span className="text-amber-800/80 text-xs">·</span>
      <span className="text-amber-200/50 text-xs">Final: Spain 1–0 Argentina (AET)</span>
      <span className="text-amber-800/80 text-xs hidden sm:inline">·</span>
      <span className="text-amber-200/35 text-xs hidden sm:inline">Tournament archive · Jul 19 2026</span>
    </div>
  )
}
