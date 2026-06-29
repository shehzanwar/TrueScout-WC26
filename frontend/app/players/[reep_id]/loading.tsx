export default function Loading() {
  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Back link */}
      <div className="h-4 w-24 bg-slate-800 rounded animate-pulse" />

      {/* Header */}
      <div className="flex justify-between items-start">
        <div className="space-y-2">
          <div className="h-7 w-48 bg-slate-800 rounded-md animate-pulse" />
          <div className="h-4 w-64 bg-slate-800/60 rounded animate-pulse" />
        </div>
        <div className="h-7 w-36 bg-slate-800 rounded-full animate-pulse" />
      </div>

      {/* Two-column grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Bayesian stats */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-3">
          <div className="h-4 w-32 bg-slate-800 rounded animate-pulse mb-3" />
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex justify-between py-2 border-b border-slate-800">
              <div className="h-3 w-24 bg-slate-800 rounded animate-pulse" />
              <div className="h-3 w-20 bg-slate-800 rounded animate-pulse" />
            </div>
          ))}
          <div className="h-2 bg-slate-800 rounded-full animate-pulse mt-3" />
        </div>

        {/* Radar */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="h-4 w-36 bg-slate-800 rounded animate-pulse mb-4" />
          <div className="h-56 bg-slate-800/30 rounded-lg animate-pulse" />
        </div>
      </div>

      {/* Tactical Analysis */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-3">
        <div className="h-4 w-32 bg-slate-800 rounded animate-pulse" />
        {[80, 95, 88, 72, 60].map((w, i) => (
          <div
            key={i}
            className="h-3 bg-slate-800 rounded animate-pulse"
            style={{ width: `${w}%` }}
          />
        ))}
        <div className="h-10 bg-slate-800 rounded-lg animate-pulse mt-2" />
      </div>
    </div>
  )
}
