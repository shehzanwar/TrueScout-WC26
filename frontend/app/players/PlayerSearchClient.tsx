"use client"

import { useState, useEffect, useRef, useCallback } from "react"
import Link from "next/link"
import { searchPlayers, type PlayerSearchResult } from "@/lib/api"

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const FLAGS: Record<string, string> = {
  Argentina: "🇦🇷", Australia: "🇦🇺", Austria: "🇦🇹", Belgium: "🇧🇪",
  Bolivia: "🇧🇴", Brazil: "🇧🇷", Cameroon: "🇨🇲", Canada: "🇨🇦",
  Chile: "🇨🇱", Colombia: "🇨🇴", "Costa Rica": "🇨🇷", Croatia: "🇭🇷",
  Denmark: "🇩🇰", Ecuador: "🇪🇨", Egypt: "🇪🇬", England: "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
  France: "🇫🇷", Germany: "🇩🇪", Ghana: "🇬🇭", Honduras: "🇭🇳",
  Hungary: "🇭🇺", Indonesia: "🇮🇩", Iran: "🇮🇷", Japan: "🇯🇵",
  "Korea Republic": "🇰🇷", "South Korea": "🇰🇷", Mexico: "🇲🇽",
  Morocco: "🇲🇦", Netherlands: "🇳🇱", "New Zealand": "🇳🇿", Nigeria: "🇳🇬",
  Panama: "🇵🇦", Paraguay: "🇵🇾", Peru: "🇵🇪", Poland: "🇵🇱",
  Portugal: "🇵🇹", Qatar: "🇶🇦", Romania: "🇷🇴", "Saudi Arabia": "🇸🇦",
  Scotland: "🏴󠁧󠁢󠁳󠁣󠁴󠁿", Senegal: "🇸🇳", Serbia: "🇷🇸", Slovenia: "🇸🇮",
  Spain: "🇪🇸", Switzerland: "🇨🇭", Tunisia: "🇹🇳", Turkey: "🇹🇷",
  Türkiye: "🇹🇷", Ukraine: "🇺🇦", "United States": "🇺🇸", USA: "🇺🇸",
  Uruguay: "🇺🇾", Venezuela: "🇻🇪", Wales: "🏴󠁧󠁢󠁷󠁬󠁳󠁿",
}

function flag(nat: string | null): string {
  return nat ? (FLAGS[nat] ?? "") : ""
}

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
// Sub-components
// ---------------------------------------------------------------------------

function SearchResultRow({ player }: { player: PlayerSearchResult }) {
  const conf = confidenceLabel(player.confidence_score)
  return (
    <Link
      href={`/players/${player.reep_id}`}
      className="flex items-center gap-3 px-4 py-3 hover:bg-slate-800 rounded-lg transition-colors group"
    >
      {/* Flag */}
      <span className="text-xl w-8 shrink-0">{flag(player.nationality)}</span>

      {/* Name + position */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-slate-100 truncate group-hover:text-emerald-400 transition-colors">
          {player.name ?? player.reep_id}
        </p>
        <p className="text-xs text-slate-500 truncate">
          {player.nationality} · {player.position_micro ?? player.position_macro}
        </p>
      </div>

      {/* Posterior rating */}
      <div className="text-right shrink-0">
        <p className={`text-sm font-bold tabular-nums ${ratingColor(player.percentile_rank)}`}>
          {player.posterior_mean.toFixed(2)}
        </p>
        <p className={`text-[11px] ${conf.color}`}>{conf.label}</p>
      </div>

      <svg
        viewBox="0 0 16 16"
        fill="currentColor"
        className="w-3.5 h-3.5 text-slate-700 group-hover:text-slate-400 shrink-0 transition-colors"
      >
        <path
          fillRule="evenodd"
          d="M6.22 4.22a.75.75 0 0 1 1.06 0l3.25 3.25a.75.75 0 0 1 0 1.06l-3.25 3.25a.75.75 0 0 1-1.06-1.06L8.94 8 6.22 5.28a.75.75 0 0 1 0-1.06Z"
          clipRule="evenodd"
        />
      </svg>
    </Link>
  )
}

function EmptyState({ query }: { query: string }) {
  return (
    <div className="py-12 flex flex-col items-center gap-2 text-center">
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        className="w-8 h-8 text-slate-700"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z"
        />
      </svg>
      <p className="text-slate-500 text-sm">No players found for "{query}"</p>
      <p className="text-slate-700 text-xs">
        Try the accented spelling — e.g. "Mbappé" not "Mbappe"
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

export default function PlayerSearchClient({ initialQ }: { initialQ: string }) {
  const [query, setQuery] = useState(initialQ)
  const [results, setResults] = useState<PlayerSearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

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

  // Run initial search on mount if initialQ provided
  useEffect(() => {
    if (initialQ.trim().length >= 2) doSearch(initialQ)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="space-y-4">
      {/* Search input */}
      <div className="relative">
        <svg
          viewBox="0 0 20 20"
          fill="currentColor"
          className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 pointer-events-none"
        >
          <path
            fillRule="evenodd"
            d="M9 3.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11ZM2 9a7 7 0 1 1 12.452 4.391l3.328 3.329a.75.75 0 1 1-1.06 1.06l-3.329-3.328A7 7 0 0 1 2 9Z"
            clipRule="evenodd"
          />
        </svg>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by player name — e.g. Rodri, Vinícius, Bellingham…"
          className="w-full bg-slate-900 border border-slate-700 rounded-xl pl-10 pr-4 py-3 text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none focus:border-emerald-500/60 focus:ring-1 focus:ring-emerald-500/20 transition"
          autoFocus
        />
        {loading && (
          <div className="absolute right-3.5 top-1/2 -translate-y-1/2">
            <div className="w-4 h-4 border-2 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin" />
          </div>
        )}
      </div>

      {/* Column headers */}
      {results.length > 0 && (
        <div className="flex items-center gap-3 px-4 pb-1 border-b border-slate-800">
          <span className="w-8 shrink-0" />
          <span className="flex-1 text-[11px] uppercase tracking-wider text-slate-600">Player</span>
          <span className="text-[11px] uppercase tracking-wider text-slate-600 text-right shrink-0">
            Posterior / Confidence
          </span>
          <span className="w-3.5 shrink-0" />
        </div>
      )}

      {/* Results */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
        {query.trim().length < 2 ? (
          <div className="py-16 flex flex-col items-center gap-2 text-center">
            <p className="text-slate-600 text-sm">Start typing to search 3,274 WC 2026 players</p>
          </div>
        ) : loading && !results.length ? (
          <div className="py-16 flex items-center justify-center">
            <div className="w-5 h-5 border-2 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin" />
          </div>
        ) : searched && results.length === 0 ? (
          <EmptyState query={query} />
        ) : (
          <div className="divide-y divide-slate-800/50 p-1">
            {results.map((p) => (
              <SearchResultRow key={p.reep_id} player={p} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
