export default function Loading() {
  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* Header */}
      <div className="space-y-1.5">
        <div className="h-7 w-36 bg-slate-800 rounded-md animate-pulse" />
        <div className="h-4 w-64 bg-slate-800/60 rounded animate-pulse" />
      </div>

      {/* Search input skeleton */}
      <div className="h-12 bg-slate-900 border border-slate-800 rounded-xl animate-pulse" />

      {/* Results skeleton */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden p-1 space-y-px">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="flex items-center gap-3 px-4 py-3">
            <div className="w-8 h-6 bg-slate-800 rounded animate-pulse shrink-0" />
            <div className="flex-1 space-y-1.5">
              <div className="h-3.5 w-32 bg-slate-800 rounded animate-pulse" />
              <div className="h-3 w-24 bg-slate-800/60 rounded animate-pulse" />
            </div>
            <div className="space-y-1.5 items-end flex flex-col shrink-0">
              <div className="h-3.5 w-10 bg-slate-800 rounded animate-pulse" />
              <div className="h-3 w-12 bg-slate-800/60 rounded animate-pulse" />
            </div>
            <div className="w-3.5 h-3.5 bg-slate-800 rounded animate-pulse shrink-0" />
          </div>
        ))}
      </div>
    </div>
  )
}
