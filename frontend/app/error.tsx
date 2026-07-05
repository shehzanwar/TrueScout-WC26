"use client"

import { useEffect } from "react"

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error(error)
  }, [error])

  return (
    <div className="flex flex-col items-center justify-center min-h-[50vh] gap-4 text-center px-4">
      <h2 className="text-lg font-semibold text-slate-100">Something went wrong</h2>
      <p className="text-sm text-slate-500 max-w-sm">
        {error.message ?? "An unexpected error occurred loading this page."}
      </p>
      <button
        onClick={reset}
        className="px-4 py-2 text-sm font-medium rounded-lg bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 transition-colors"
      >
        Try again
      </button>
    </div>
  )
}
