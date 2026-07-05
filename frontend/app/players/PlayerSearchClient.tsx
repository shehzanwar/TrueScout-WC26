"use client"

import { useState, useEffect, useRef, useCallback } from "react"
import Link from "next/link"
import { searchPlayers, playerSlug, type PlayerSearchResult } from "@/lib/api"
import FifaBadge from "./FifaBadge"
import { FlagIcon } from "@/app/components/FlagIcon"

function confidenceLabel(score: number): { label: string; color: string } {
  if (score >= 0.7) return { label: "High", color: "text-emerald-400" }
  if (score >= 0.4) return { label: "Moderate", color: "text-amber-400" }
  return { label: "Sparse", color: "text-rose-400" }
}

function ratingColor(pct: number): string {
  if (pct >= 0.75) return "text-emerald-400"
  if (pct >= 0.4) return "text-slate-200"
  return "text-slate-500"
}

// ---------------------------------------------------------------------------
// Sortable table (lg+)
// ---------------------------------------------------------------------------

type SortKey = "truescout_rating" | "position_macro" | "national_team" | "confidence_score"
type SortDir = "asc" | "desc"

function SortIcon({ active, dir }: { active: boolean; dir: SortDir }) {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" className={`w-3 h-3 transition-opacity ${active ? "opacity-100" : "opacity-30"}`}>
      {dir === "desc" || !active ? (
        <path d="M8 3a.75.75 0 0 1 .75.75v6.69l2.22-2.22a.75.75 0 1 1 1.06 1.06l-3.5 3.5a.75.75 0 0 1-1.06 0l-3.5-3.5a.75.75 0 1 1 1.06-1.06L7.25 10.44V3.75A.75.75 0 0 1 8 3Z" />
      ) : (
        <path d="M8 13a.75.75 0 0 1-.75-.75V5.56L5.03 7.78a.75.75 0 0 1-1.06-1.06l3.5-3.5a.75.75 0 0 1 1.06 0l3.5 3.5a.75.75 0 0 1-1.06 1.06L8.75 5.56v6.69A.75.75 0 0 1 8 13Z" />
      )}
    </svg>
  )
}

function ThButton({
  label,
  sortKey,
  currentKey,
  currentDir,
  onClick,
  align = "left",
}: {
  label: string
  sortKey: SortKey
  currentKey: SortKey
  currentDir: SortDir
  onClick: (k: SortKey) => void
  align?: "left" | "right"
}) {
  const active = currentKey === sortKey
  return (
    <button
      onClick={() => onClick(sortKey)}
      className={`flex items-center gap-1 text-[11px] uppercase tracking-wider font-medium transition-colors ${
        active ? "text-emerald-400" : "text-slate-500 hover:text-slate-300"
      } ${align === "right" ? "ml-auto" : ""}`}
    >
      {label}
      <SortIcon active={active} dir={active ? currentDir : "desc"} />
    </button>
  )
}

function SortableTable({
  results,
  sortKey,
  sortDir,
  onSort,
}: {
  results: PlayerSearchResult[]
  sortKey: SortKey
  sortDir: SortDir
  onSort: (k: SortKey) => void
}) {
  return (
    <div className="w-full overflow-x-auto rounded-xl border border-slate-800">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b border-slate-800 bg-slate-900/80">
            <th className="px-4 py-2.5 text-left w-8 shrink-0" />
            <th className="px-4 py-2.5 text-left">
              <span className="text-[11px] uppercase tracking-wider text-slate-500 font-medium">Player</span>
            </th>
            <th className="px-4 py-2.5 text-left hidden xl:table-cell">
              <ThButton label="Nation" sortKey="national_team" currentKey={sortKey} currentDir={sortDir} onClick={onSort} />
            </th>
            <th className="px-4 py-2.5 text-left">
              <ThButton label="Position" sortKey="position_macro" currentKey={sortKey} currentDir={sortDir} onClick={onSort} />
            </th>
            <th className="px-4 py-2.5 text-right">
              <ThButton label="Rating" sortKey="truescout_rating" currentKey={sortKey} currentDir={sortDir} onClick={onSort} align="right" />
            </th>
            <th className="px-4 py-2.5 text-right hidden xl:table-cell">
              <ThButton label="Data" sortKey="confidence_score" currentKey={sortKey} currentDir={sortDir} onClick={onSort} align="right" />
            </th>
            <th className="w-6 px-2" />
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/50 bg-slate-900">
          {results.map((p) => {
            const conf = confidenceLabel(p.confidence_score)
            return (
              <tr
                key={p.reep_id}
                className="group hover:bg-slate-800/60 transition-colors cursor-pointer"
                onClick={() => window.location.href = `/players/${playerSlug(p)}`}
              >
                {/* Flag */}
                <td className="px-4 py-2.5">
                  <FlagIcon name={p.national_team ?? p.nationality} size={18} />
                </td>
                {/* Name */}
                <td className="px-4 py-2.5 max-w-[180px]">
                  <Link
                    href={`/players/${playerSlug(p)}`}
                    className="font-medium text-slate-100 group-hover:text-emerald-400 transition-colors truncate block"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {p.name ?? p.reep_id}
                  </Link>
                </td>
                {/* Nation */}
                <td className="px-4 py-2.5 text-slate-400 hidden xl:table-cell whitespace-nowrap">
                  {p.national_team ?? p.nationality ?? "—"}
                </td>
                {/* Position */}
                <td className="px-4 py-2.5 text-slate-400 whitespace-nowrap">
                  {p.position_micro ?? p.position_macro}
                </td>
                {/* Rating */}
                <td className="px-4 py-2.5 text-right">
                  <div className="flex items-center justify-end gap-2">
                    <FifaBadge fifa={p.fifa} size="sm" />
                    <span className={`tabular-nums font-mono text-sm ${ratingColor(p.percentile_rank)}`}>
                      {p.truescout_rating.toFixed(2)}
                    </span>
                  </div>
                </td>
                {/* Data quality */}
                <td className={`px-4 py-2.5 text-right text-xs hidden xl:table-cell ${conf.color}`}>
                  {conf.label}
                </td>
                {/* Arrow */}
                <td className="px-2 py-2.5 text-slate-700 group-hover:text-slate-400 transition-colors">
                  <svg viewBox="0 0 16 16" fill="currentColor" className="w-3.5 h-3.5">
                    <path fillRule="evenodd" d="M6.22 4.22a.75.75 0 0 1 1.06 0l3.25 3.25a.75.75 0 0 1 0 1.06l-3.25 3.25a.75.75 0 0 1-1.06-1.06L8.94 8 6.22 5.28a.75.75 0 0 1 0-1.06Z" clipRule="evenodd" />
                  </svg>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Mobile card list
// ---------------------------------------------------------------------------

function SearchResultRow({ player }: { player: PlayerSearchResult }) {
  const conf = confidenceLabel(player.confidence_score)
  return (
    <Link
      href={`/players/${playerSlug(player)}`}
      className="flex items-center gap-3 px-4 py-3 hover:bg-slate-800 rounded-lg transition-colors group"
    >
      <span className="w-8 shrink-0 flex items-center"><FlagIcon name={player.national_team ?? player.nationality} size={20} /></span>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-slate-100 truncate group-hover:text-emerald-400 transition-colors">
          {player.name ?? player.reep_id}
        </p>
        <p className="text-xs text-slate-500 truncate">
          {player.national_team ?? player.nationality} · {player.position_micro ?? player.position_macro}
        </p>
      </div>
      <div className="flex flex-col items-end gap-0.5 shrink-0">
        <FifaBadge fifa={player.fifa} size="sm" />
        <p className={`text-[11px] tabular-nums ${ratingColor(player.percentile_rank)}`}>
          {player.truescout_rating.toFixed(2)}/10
        </p>
        <p className={`text-[10px] ${conf.color}`}>{conf.label}</p>
      </div>
      <svg viewBox="0 0 16 16" fill="currentColor" className="w-3.5 h-3.5 text-slate-700 group-hover:text-slate-400 shrink-0 transition-colors">
        <path fillRule="evenodd" d="M6.22 4.22a.75.75 0 0 1 1.06 0l3.25 3.25a.75.75 0 0 1 0 1.06l-3.25 3.25a.75.75 0 0 1-1.06-1.06L8.94 8 6.22 5.28a.75.75 0 0 1 0-1.06Z" clipRule="evenodd" />
      </svg>
    </Link>
  )
}

function EmptyState({ query }: { query: string }) {
  return (
    <div className="py-12 flex flex-col items-center gap-2 text-center">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className="w-8 h-8 text-slate-700">
        <path strokeLinecap="round" strokeLinejoin="round" d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z" />
      </svg>
      <p className="text-slate-500 text-sm">No players found for &ldquo;{query}&rdquo;</p>
      <p className="text-slate-700 text-xs">Try a shorter name — e.g. &ldquo;Mbappe&rdquo;, &ldquo;Vini&rdquo;, &ldquo;Rodri&rdquo;</p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

function sortResults(
  results: PlayerSearchResult[],
  key: SortKey,
  dir: SortDir,
): PlayerSearchResult[] {
  return [...results].sort((a, b) => {
    let av: string | number
    let bv: string | number
    if (key === "national_team") {
      av = (a.national_team ?? a.nationality ?? "").toLowerCase()
      bv = (b.national_team ?? b.nationality ?? "").toLowerCase()
    } else if (key === "position_macro") {
      av = (a.position_micro ?? a.position_macro ?? "").toLowerCase()
      bv = (b.position_micro ?? b.position_macro ?? "").toLowerCase()
    } else {
      av = a[key] as number
      bv = b[key] as number
    }
    if (av < bv) return dir === "asc" ? -1 : 1
    if (av > bv) return dir === "asc" ? 1 : -1
    return 0
  })
}

export default function PlayerSearchClient({ initialQ }: { initialQ: string }) {
  const [query, setQuery]     = useState(initialQ)
  const [results, setResults] = useState<PlayerSearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)
  const [sortKey, setSortKey] = useState<SortKey>("truescout_rating")
  const [sortDir, setSortDir] = useState<SortDir>("desc")
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const doSearch = useCallback(async (q: string) => {
    if (q.trim().length < 2) {
      setResults([])
      setSearched(false)
      return
    }
    setLoading(true)
    try {
      const data = await searchPlayers(q)
      setResults(data)
      setSearched(true)
    } catch {
      setResults([])
      setSearched(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => doSearch(query), 350)
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [query, doSearch])

  useEffect(() => {
    if (initialQ.trim().length >= 2) doSearch(initialQ)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Keyboard shortcut: "/" focuses search from anywhere on the page
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "/" && document.activeElement !== inputRef.current) {
        e.preventDefault()
        inputRef.current?.focus()
      }
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [])

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"))
    } else {
      setSortKey(key)
      setSortDir("desc")
    }
  }

  const sorted = sortResults(results, sortKey, sortDir)

  return (
    <div className="space-y-4">
      {/* Search input */}
      <div className="relative">
        <svg
          viewBox="0 0 20 20"
          fill="currentColor"
          className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 pointer-events-none"
        >
          <path fillRule="evenodd" d="M9 3.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11ZM2 9a7 7 0 1 1 12.452 4.391l3.328 3.329a.75.75 0 1 1-1.06 1.06l-3.329-3.328A7 7 0 0 1 2 9Z" clipRule="evenodd" />
        </svg>
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by player name — e.g. Rodri, Vinícius, Bellingham… (press / to focus)"
          className="w-full bg-slate-900 border border-slate-700 rounded-xl pl-10 pr-4 py-3 text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none focus:border-emerald-500/60 focus:ring-1 focus:ring-emerald-500/20 transition"
          autoFocus
        />
        {loading && (
          <div className="absolute right-3.5 top-1/2 -translate-y-1/2">
            <div className="w-4 h-4 border-2 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin" />
          </div>
        )}
      </div>

      {/* Results */}
      {query.trim().length < 2 ? (
        <div className="bg-slate-900 border border-slate-800 rounded-xl py-16 flex flex-col items-center gap-2 text-center">
          <p className="text-slate-600 text-sm">Start typing to search 3,274 WC 2026 players</p>
        </div>
      ) : loading && !results.length ? (
        <div className="bg-slate-900 border border-slate-800 rounded-xl py-16 flex items-center justify-center">
          <div className="w-5 h-5 border-2 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin" />
        </div>
      ) : searched && results.length === 0 ? (
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
          <EmptyState query={query} />
        </div>
      ) : sorted.length > 0 ? (
        <>
          {/* Desktop: sortable table */}
          <div className="hidden lg:block">
            <SortableTable results={sorted} sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
            <p className="text-[10px] text-slate-700 mt-2 text-right">{sorted.length} players · click a column header to sort</p>
          </div>

          {/* Mobile: card list */}
          <div className="lg:hidden bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
            <div className="flex items-center gap-3 px-4 pb-2 pt-3 border-b border-slate-800">
              <span className="w-8 shrink-0" />
              <span className="flex-1 text-[11px] uppercase tracking-wider text-slate-600">Player</span>
              <span className="text-[11px] uppercase tracking-wider text-slate-600 text-right shrink-0">Rating / Data</span>
              <span className="w-3.5 shrink-0" />
            </div>
            <div className="divide-y divide-slate-800/50 p-1">
              {results.map((p) => (
                <SearchResultRow key={p.reep_id} player={p} />
              ))}
            </div>
          </div>
        </>
      ) : null}
    </div>
  )
}
