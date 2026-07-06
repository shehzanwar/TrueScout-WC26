"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { NAV } from "@/lib/navigation"

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
        <div className="flex gap-3">
          <Link
            href="/about"
            className="text-xs text-slate-600 hover:text-slate-400 transition-colors"
          >
            About
          </Link>
          <span className="text-slate-700">·</span>
          <Link
            href="/methodology"
            className="text-xs text-slate-600 hover:text-slate-400 transition-colors"
          >
            Methodology
          </Link>
        </div>
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
