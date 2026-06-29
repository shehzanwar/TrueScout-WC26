export default function Loading() {
  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="space-y-1.5">
        <div className="h-7 w-28 bg-slate-800 rounded-md animate-pulse" />
        <div className="h-4 w-64 bg-slate-800/60 rounded animate-pulse" />
      </div>

      {/* Round selector */}
      <div className="flex flex-wrap gap-2">
        {[112, 104, 120, 104, 60].map((w, i) => (
          <div
            key={i}
            className="h-8 bg-slate-800 rounded-lg animate-pulse"
            style={{ width: w }}
          />
        ))}
      </div>

      {/* Card grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-4"
          >
            {/* Card header */}
            <div className="flex justify-between">
              <div className="h-3 w-14 bg-slate-800 rounded animate-pulse" />
              <div className="h-3 w-16 bg-slate-800 rounded animate-pulse" />
            </div>

            {/* Teams */}
            <div className="flex items-center gap-3">
              <div className="flex-1 space-y-1.5">
                <div className="h-6 w-6 bg-slate-800 rounded animate-pulse" />
                <div className="h-4 w-20 bg-slate-800 rounded animate-pulse" />
              </div>
              <div className="h-4 w-8 bg-slate-800 rounded animate-pulse" />
              <div className="flex-1 flex flex-col items-end space-y-1.5">
                <div className="h-6 w-6 bg-slate-800 rounded animate-pulse" />
                <div className="h-4 w-20 bg-slate-800 rounded animate-pulse" />
              </div>
            </div>

            {/* Prob bars */}
            <div className="border-t border-slate-800 pt-3 space-y-2.5">
              {[0, 1].map((j) => (
                <div key={j} className="flex items-center gap-2.5">
                  <div className="h-2.5 w-16 bg-slate-800 rounded animate-pulse" />
                  <div className="h-1.5 flex-1 bg-slate-800 rounded-full animate-pulse" />
                  <div className="h-2.5 w-8 bg-slate-800 rounded animate-pulse" />
                  <div className="h-2.5 w-3 bg-slate-800 rounded animate-pulse" />
                  <div className="h-2.5 w-8 bg-slate-800 rounded animate-pulse" />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
