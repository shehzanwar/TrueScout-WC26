"use client"

import { motion } from "framer-motion"
import type { Matchup } from "@/lib/api"
import MatchCard from "@/app/components/MatchCard"

const container = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.07 },
  },
}

export default function MatchCardGrid({ matches }: { matches: Matchup[] }) {
  return (
    <motion.div
      variants={container}
      initial="hidden"
      animate="show"
      className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4"
    >
      {matches.map((match) => (
        <MatchCard key={match.event_id} match={match} />
      ))}
    </motion.div>
  )
}
