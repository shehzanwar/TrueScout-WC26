export default function Loading() {
  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Header skeleton */}
      <div className="space-y-2">
        <div className="h-7 w-36 bg-slate-800 rounded-md animate-pulse" />
        <div className="h-4 w-64 bg-slate-800/60 rounded animate-pulse" />
      </div>

      {/* Cards skeleton */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {[0, 1].map((i) => (
          <div
            key={i}
            className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4"
          >
            {/* Card title */}
            <div className="space-y-1.5">
              <div className="h-4 w-28 bg-slate-800 rounded animate-pulse" />
              <div className="h-3 w-48 bg-slate-800/50 rounded animate-pulse" />
            </div>

            {/* Card rows */}
            {Array.from({ length: 5 }).map((_, j) => (
              <div key={j} className="flex items-center gap-3">
                <div className="w-5 h-3 bg-slate-800 rounded animate-pulse" />
                <div className="flex-1 space-y-1.5">
                  <div className="flex justify-between">
                    <div className="h-3.5 w-28 bg-slate-800 rounded animate-pulse" />
                    <div className="h-3.5 w-10 bg-slate-800/60 rounded animate-pulse" />
                  </div>
                  <div className="h-1 bg-slate-800 rounded-full animate-pulse" />
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}
