export default function Loading() {
  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="space-y-1.5">
        <div className="h-7 w-52 bg-slate-800 rounded-md animate-pulse" />
        <div className="h-4 w-80 bg-slate-800/60 rounded animate-pulse" />
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-3 animate-pulse">
            <div className="h-3 w-24 bg-slate-800 rounded" />
            <div className="space-y-2.5">
              {[90, 80, 70].map((w, j) => (
                <div key={j} className="flex justify-between">
                  <div className="h-3 bg-slate-800 rounded" style={{ width: `${w * 0.45}%` }} />
                  <div className="h-3 w-16 bg-slate-800 rounded" />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Two-column content */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        {/* Scatter skeleton */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-3 animate-pulse">
          <div className="h-3 w-36 bg-slate-800 rounded" />
          <div className="h-[320px] bg-slate-800/30 rounded-lg" />
        </div>

        {/* Table skeleton */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden animate-pulse">
          <div className="px-5 pt-5 pb-3 border-b border-slate-800 space-y-2">
            <div className="h-3 w-24 bg-slate-800 rounded" />
            <div className="h-3 w-48 bg-slate-800/60 rounded" />
          </div>
          <div className="divide-y divide-slate-800/50">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="flex items-center gap-4 px-5 py-3">
                <div className="h-3 w-8 bg-slate-800 rounded shrink-0" />
                <div className="flex-1 h-3 bg-slate-800/60 rounded" />
                <div className="h-3 w-12 bg-slate-800 rounded shrink-0" />
                <div className="h-3 w-10 bg-slate-800/60 rounded shrink-0" />
                <div className="h-3 w-14 bg-slate-800 rounded shrink-0" />
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
