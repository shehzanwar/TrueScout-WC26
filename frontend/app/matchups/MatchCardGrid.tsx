"use client"

import type { Matchup } from "@/lib/api"
import MatchCard from "@/app/components/MatchCard"

export default function MatchCardGrid({ matches }: { matches: Matchup[] }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      {matches.map((match) => (
        <MatchCard key={match.event_id} match={match} />
      ))}
    </div>
  )
}
