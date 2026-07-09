"use client"
import { useState, useEffect } from "react"

export default function StaleDataBanner({ runDate }: { runDate?: string }) {
  const [hoursAgo, setHoursAgo] = useState<number | null>(null)
  const [dismissed, setDismissed] = useState(false)

  useEffect(() => {
    if (!runDate) return
    try {
      // run_date is "YYYY-MM-DD" — treat midnight UTC as the reference point
      const rd = new Date(runDate + "T00:00:00Z")
      const diff = (Date.now() - rd.getTime()) / 3_600_000
      setHoursAgo(Math.round(diff))
    } catch {
      // ignore invalid date
    }
  }, [runDate])

  if (!hoursAgo || hoursAgo <= 48 || dismissed) return null

  const daysAgo = Math.round(hoursAgo / 24)
  const label = daysAgo >= 2 ? `${daysAgo} days` : `${hoursAgo} hours`

  return (
    <div className="flex items-center gap-3 rounded-lg border border-amber-500/30 bg-amber-900/20 px-4 py-2.5 text-sm text-amber-300 mb-6">
      <span className="shrink-0 text-amber-400">&#9888;</span>
      <span>
        Model last updated <strong>{label} ago</strong> — live results may not be reflected yet.
      </span>
      <button
        onClick={() => setDismissed(true)}
        className="ml-auto shrink-0 opacity-60 hover:opacity-100 transition-opacity"
        aria-label="Dismiss"
      >
        &#10005;
      </button>
    </div>
  )
}
