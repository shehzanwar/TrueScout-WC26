"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"

const NAV = [
  {
    href: "/",
    label: "Dashboard",
    tagline: "Tournament overview",
    icon: (
      <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
        <path d="M2 10a8 8 0 1 1 16 0A8 8 0 0 1 2 10Zm8-3a1 1 0 0 0 0 2h.01a1 1 0 0 0 0-2H10Zm0 4a1 1 0 0 0-1 1v2a1 1 0 1 0 2 0v-2a1 1 0 0 0-1-1Z" />
      </svg>
    ),
  },
  {
    href: "/bracket",
    label: "Knockout Tree",
    tagline: "Predictions for every match",
    icon: (
      <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
        <path fillRule="evenodd" d="M2 4.75A.75.75 0 0 1 2.75 4h14.5a.75.75 0 0 1 0 1.5H2.75A.75.75 0 0 1 2 4.75Zm0 10.5a.75.75 0 0 1 .75-.75h7.5a.75.75 0 0 1 0 1.5h-7.5a.75.75 0 0 1-.75-.75ZM2 10a.75.75 0 0 1 .75-.75h14.5a.75.75 0 0 1 0 1.5H2.75A.75.75 0 0 1 2 10Z" clipRule="evenodd" />
      </svg>
    ),
  },
  {
    href: "/matchups",
    label: "Matchups",
    tagline: "Today's games and odds",
    icon: (
      <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
        <path d="M10 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z" />
        <path fillRule="evenodd" d="M.664 10.59a1.651 1.651 0 0 1 0-1.186A10.004 10.004 0 0 1 10 3c4.257 0 7.893 2.66 9.336 6.41.147.381.146.804 0 1.186A10.004 10.004 0 0 1 10 17c-4.257 0-7.893-2.66-9.336-6.41Z" clipRule="evenodd" />
      </svg>
    ),
  },
  {
    href: "/nations",
    label: "Nations",
    tagline: "32-team knockout squads",
    icon: (
      <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
        <path fillRule="evenodd" d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Zm-1.503.204A6.5 6.5 0 1 1 4.225 6.838c.12.296.295.56.5.787l.034.038.038.033A1.5 1.5 0 0 1 5 9c0 .828.545 1.521 1.294 1.757l.535.174.286.857A1.503 1.503 0 0 0 8.547 13H10a1.5 1.5 0 0 0 1.5-1.5v-.5a.5.5 0 0 1 .5-.5h1a1 1 0 0 0 .8-.4l.5-.667A.5.5 0 0 1 14.7 9.2l.644.483A6.515 6.515 0 0 1 16.497 10.204Z" clipRule="evenodd" />
      </svg>
    ),
  },
  {
    href: "/players",
    label: "Player Search",
    tagline: "Find any player",
    icon: (
      <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
        <path d="M10 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM3.465 14.493a1.23 1.23 0 0 0 .41 1.412A9.957 9.957 0 0 0 10 18c2.31 0 4.438-.784 6.131-2.1.43-.333.604-.903.408-1.41a7.002 7.002 0 0 0-13.074.003Z" />
      </svg>
    ),
  },
  {
    href: "/compare",
    label: "Compare",
    tagline: "Side-by-side player verdicts",
    icon: (
      <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
        <path fillRule="evenodd" d="M10 2a.75.75 0 0 1 .75.75v.258a33.186 33.186 0 0 1 6.668 2.373.75.75 0 1 1-.636 1.351 31.665 31.665 0 0 0-6.032-2.171V10.5a1 1 0 0 1-2 0V4.561a31.67 31.67 0 0 0-6.032 2.17.75.75 0 0 1-.636-1.35A33.19 33.19 0 0 1 9.25 3.008V2.75A.75.75 0 0 1 10 2ZM3.265 9.852a.75.75 0 0 1 1.017.298A7.5 7.5 0 0 0 10 13.5a7.5 7.5 0 0 0 5.718-3.35.75.75 0 1 1 1.315.718A9 9 0 0 1 10 15a9 9 0 0 1-6.982-3.532.75.75 0 0 1-.753-1.616Z" clipRule="evenodd" />
      </svg>
    ),
  },
  {
    href: "/brier",
    label: "Model Calibration",
    tagline: "How accurate are we?",
    icon: (
      <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
        <path fillRule="evenodd" d="M15.312 11.424a5.5 5.5 0 0 1-9.201 2.466l-.312-.311h2.433a.75.75 0 0 0 0-1.5H3.989a.75.75 0 0 0-.75.75v4.242a.75.75 0 0 0 1.5 0v-2.43l.31.31a7 7 0 0 0 11.712-3.138.75.75 0 0 0-1.449-.39Zm1.23-3.723a.75.75 0 0 0 .219-.53V2.929a.75.75 0 0 0-1.5 0V5.36l-.31-.31A7 7 0 0 0 3.239 8.188a.75.75 0 1 0 1.448.389A5.5 5.5 0 0 1 13.89 6.11l.311.31h-2.432a.75.75 0 0 0 0 1.5h4.243a.75.75 0 0 0 .53-.219Z" clipRule="evenodd" />
      </svg>
    ),
  },
]

function formatDate(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number)
  const d = new Date(year, month - 1, day)
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
}

export default function Sidebar({ lastUpdated }: { lastUpdated?: string }) {
  const pathname = usePathname()

  return (
    <aside className="hidden lg:flex w-56 shrink-0 flex-col bg-slate-900 border-r border-slate-800 min-h-screen">
      {/* Brand */}
      <div className="px-5 py-5 border-b border-slate-800">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-emerald-500 flex items-center justify-center shrink-0">
            <svg viewBox="0 0 20 20" fill="white" className="w-4 h-4">
              <path d="M10 2a8 8 0 1 0 0 16A8 8 0 0 0 10 2Zm0 3a1 1 0 0 1 1 1v3.586l2.121 2.121a1 1 0 1 1-1.414 1.414l-2.414-2.414A1 1 0 0 1 9 10V6a1 1 0 0 1 1-1Z" />
            </svg>
          </div>
          <span className="font-semibold text-slate-100 tracking-tight">TrueScout</span>
        </div>
        <p className="mt-1 text-xs text-slate-500">WC 2026 Intelligence</p>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {NAV.map(({ href, label, tagline, icon }) => {
          const active = pathname === href
          return (
            <Link
              key={href}
              href={href}
              className={[
                "flex items-start gap-3 px-3 py-2 rounded-lg transition-colors",
                active
                  ? "bg-emerald-500/15 text-emerald-400"
                  : "text-slate-400 hover:text-slate-100 hover:bg-slate-800",
              ].join(" ")}
            >
              <span className={`mt-0.5 shrink-0 ${active ? "text-emerald-400" : "text-slate-500"}`}>
                {icon}
              </span>
              <div>
                <p className="text-sm font-medium leading-snug">{label}</p>
                <p className={`text-[10px] leading-snug mt-0.5 ${active ? "text-emerald-600" : "text-slate-600"}`}>
                  {tagline}
                </p>
              </div>
            </Link>
          )
        })}
      </nav>

      {/* Footer */}
      <div className="px-5 py-4 border-t border-slate-800 space-y-2">
        <Link
          href="/about"
          className="block text-xs text-slate-600 hover:text-slate-400 transition-colors"
        >
          About · How it works
        </Link>
        <p className="text-[10px] text-slate-600 leading-relaxed">
          Probabilities are statistical model estimates — not predictions, guarantees, or betting advice.
        </p>
        {lastUpdated && (
          <p className="text-[10px] text-slate-700">
            Updated {formatDate(lastUpdated)}
          </p>
        )}
      </div>
    </aside>
  )
}
