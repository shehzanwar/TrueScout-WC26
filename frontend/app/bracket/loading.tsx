export default function Loading() {
  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="space-y-1.5">
        <div className="h-7 w-40 bg-slate-800 rounded-md animate-pulse" />
        <div className="h-4 w-80 bg-slate-800/60 rounded animate-pulse" />
      </div>

      {/* Legend skeleton */}
      <div className="flex items-center gap-4">
        {[48, 56, 72].map((w, i) => (
          <div key={i} className="h-3 bg-slate-800/60 rounded animate-pulse" style={{ width: w }} />
        ))}
      </div>

      {/* Header row */}
      <div className="flex items-center gap-1">
        {["Round of 32", "Round of 16", "Quarterfinals", "Semifinals", "Final"].map((label, i) => (
          <div key={i} className="flex items-center gap-1">
            {i > 0 && <div className="w-8 h-3 bg-transparent" />}
            <div className="w-36 text-center">
              <div className="h-3 w-20 mx-auto bg-slate-800/60 rounded animate-pulse" />
            </div>
          </div>
        ))}
      </div>

      {/* Bracket skeleton — just show the R32 column as a list */}
      <div className="flex gap-1 overflow-hidden">
        <div className="w-40 flex flex-col gap-0.5 shrink-0">
          {Array.from({ length: 16 }).map((_, i) => (
            <div
              key={i}
              className="bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-1.5 space-y-1.5 animate-pulse"
            >
              <div className="flex items-center gap-1.5">
                <div className="w-5 h-4 bg-slate-800 rounded" />
                <div className="flex-1 h-3 bg-slate-800 rounded" />
                <div className="w-6 h-2.5 bg-slate-800 rounded" />
              </div>
              <div className="h-[3px] bg-slate-800 rounded-full" />
            </div>
          ))}
        </div>
        {/* Blurred-out future columns hint */}
        <div className="flex-1 flex items-center justify-center">
          <div className="text-xs text-slate-700 italic">Loading simulations…</div>
        </div>
      </div>
    </div>
  )
}
