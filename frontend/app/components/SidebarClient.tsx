"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { NAV } from "@/lib/navigation"

function DrawerContent({
  pathname,
  onClose,
}: {
  pathname: string
  onClose: () => void
}) {
  return (
    <>
      {/* Brand + close */}
      <div className="px-5 py-5 border-b border-slate-800 flex items-center justify-between">
        <div>
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
        <button
          onClick={onClose}
          className="p-1.5 rounded-lg text-slate-400 hover:text-slate-100 hover:bg-slate-800 transition-colors"
          aria-label="Close navigation"
        >
          <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
            <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
          </svg>
        </button>
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
          <Link href="/about" className="text-xs text-slate-600 hover:text-slate-400 transition-colors">
            About
          </Link>
          <span className="text-slate-700">·</span>
          <Link href="/methodology" className="text-xs text-slate-600 hover:text-slate-400 transition-colors">
            Methodology
          </Link>
        </div>
        <p className="text-xs text-slate-700">WC 2026 Intelligence</p>
      </div>
    </>
  )
}

export default function SidebarClient() {
  const [isOpen, setIsOpen] = useState(false)
  const pathname = usePathname()

  // Auto-close drawer on navigation
  useEffect(() => {
    setIsOpen(false)
  }, [pathname])

  // Prevent body scroll when drawer is open
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = "hidden"
    } else {
      document.body.style.overflow = ""
    }
    return () => { document.body.style.overflow = "" }
  }, [isOpen])

  return (
    <>
      {/* Mobile sticky top bar — hidden on desktop */}
      <div className="lg:hidden sticky top-0 z-30 flex items-center gap-3 px-4 py-3 bg-slate-900 border-b border-slate-800">
        <button
          onClick={() => setIsOpen(true)}
          className="p-1.5 rounded-lg text-slate-400 hover:text-slate-100 hover:bg-slate-800 transition-colors"
          aria-label="Open navigation"
          aria-expanded={isOpen}
        >
          <svg viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5">
            <path fillRule="evenodd" d="M2 4.75A.75.75 0 0 1 2.75 4h14.5a.75.75 0 0 1 0 1.5H2.75A.75.75 0 0 1 2 4.75Zm0 10.5a.75.75 0 0 1 .75-.75h7.5a.75.75 0 0 1 0 1.5h-7.5a.75.75 0 0 1-.75-.75ZM2 10a.75.75 0 0 1 .75-.75h14.5a.75.75 0 0 1 0 1.5H2.75A.75.75 0 0 1 2 10Z" clipRule="evenodd" />
          </svg>
        </button>
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-md bg-emerald-500 flex items-center justify-center shrink-0">
            <svg viewBox="0 0 20 20" fill="white" className="w-3.5 h-3.5">
              <path d="M10 2a8 8 0 1 0 0 16A8 8 0 0 0 10 2Zm0 3a1 1 0 0 1 1 1v3.586l2.121 2.121a1 1 0 1 1-1.414 1.414l-2.414-2.414A1 1 0 0 1 9 10V6a1 1 0 0 1 1-1Z" />
            </svg>
          </div>
          <span className="font-semibold text-sm text-slate-100 tracking-tight">TrueScout</span>
        </div>
      </div>

      {/* Backdrop */}
      {isOpen && (
        <div
          className="lg:hidden fixed inset-0 z-40 bg-black/60"
          aria-hidden="true"
          onClick={() => setIsOpen(false)}
        />
      )}

      {/* Slide-in drawer */}
      <aside
        className={[
          "lg:hidden fixed inset-y-0 left-0 z-50 w-56 flex flex-col bg-slate-900 border-r border-slate-800",
          "transition-transform duration-200 ease-in-out",
          isOpen ? "translate-x-0" : "-translate-x-full",
        ].join(" ")}
        aria-label="Navigation drawer"
      >
        <DrawerContent pathname={pathname} onClose={() => setIsOpen(false)} />
      </aside>
    </>
  )
}
