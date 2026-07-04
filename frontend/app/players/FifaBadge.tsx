// TrueScout Rating chip (0-99) — shared across profile page and search results.
// Intentionally no "use client" — renders in both Server and Client components.

export type FifaBand = {
  overall: number | null
  band: string
}

// Tailwind classes per band — must use full strings (no dynamic construction)
export function fifaBandStyles(band: string): { bg: string; text: string; border: string } {
  switch (band) {
    case "World Class": return { bg: "bg-purple-500/15", text: "text-purple-300", border: "border-purple-500/30" }
    case "Elite":       return { bg: "bg-amber-400/15",  text: "text-amber-300",  border: "border-amber-400/30"  }
    case "Top Tier":    return { bg: "bg-amber-500/15",  text: "text-amber-400",  border: "border-amber-500/30"  }
    case "Quality":     return { bg: "bg-emerald-500/15",text: "text-emerald-400",border: "border-emerald-500/30"}
    case "Good":        return { bg: "bg-sky-500/15",    text: "text-sky-400",    border: "border-sky-500/30"    }
    case "Decent":      return { bg: "bg-slate-500/15",  text: "text-slate-400",  border: "border-slate-500/30"  }
    default:            return { bg: "bg-slate-800",     text: "text-slate-500",  border: "border-slate-700"     }
  }
}

// Hex color for SVG / canvas usage (radar fill)
export function fifaBandColor(band: string): string {
  switch (band) {
    case "World Class": return "#a855f7"  // purple-500
    case "Elite":       return "#fbbf24"  // amber-400
    case "Top Tier":    return "#f59e0b"  // amber-500
    case "Quality":     return "#10b981"  // emerald-500
    case "Good":        return "#38bdf8"  // sky-400
    case "Decent":      return "#94a3b8"  // slate-400
    default:            return "#475569"  // slate-600
  }
}

export default function FifaBadge({
  fifa,
  size = "md",
}: {
  fifa: FifaBand | undefined | null
  size?: "sm" | "md" | "lg"
}) {
  if (!fifa || fifa.overall === null) return null
  const { bg, text, border } = fifaBandStyles(fifa.band)
  const sizeClasses = {
    sm: "px-1.5 py-0.5 text-[10px]",
    md: "px-2.5 py-1 text-xs",
    lg: "px-3 py-1.5 text-sm",
  }[size]

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full font-bold tabular-nums border ${bg} ${text} ${border} ${sizeClasses}`}
      title={`TrueScout Rating: ${fifa.overall} · ${fifa.band}`}
    >
      {fifa.overall}
      <span className="font-normal opacity-70 text-[0.8em]">{fifa.band}</span>
    </span>
  )
}
