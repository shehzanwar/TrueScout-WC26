import type { SimulationsResponse, MatchupsResponse } from "./api"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface BracketTeam {
  name: string
  advanceProb: number   // P(advance FROM this round to next) — drives the prob bar
  titleProb: number     // P(win tournament) — secondary display
  isProjected: boolean  // false only for R32 (actual ESPN fixtures)
}

export interface BracketSlot {
  top: BracketTeam
  bottom: BracketTeam
}

export interface BracketRound {
  code: string    // "R32" | "R16" | "QF" | "SF" | "F"
  label: string
  slots: BracketSlot[]
}

export interface BracketData {
  rounds: BracketRound[]
  champion: BracketTeam | null
  runDate: string
  nIterations: number
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

// NEXT[X] = the simulations round to look up P(advance FROM round X)
const NEXT: Record<string, string> = {
  R32: "R16",
  R16: "QF",
  QF:  "SF",
  SF:  "F",
  F:   "W",
}

const ROUND_LABELS: Record<string, string> = {
  R32: "Round of 32",
  R16: "Round of 16",
  QF:  "Quarterfinals",
  SF:  "Semifinals",
  F:   "Final",
}

// ---------------------------------------------------------------------------
// buildBracket
// ---------------------------------------------------------------------------

export function buildBracket(
  sim: SimulationsResponse,
  r32: MatchupsResponse,
): BracketData | null {
  if (!r32.matches.length) return null

  // Build lookup: teamName → simRound → { ap: advanceProb, tp: titleProb }
  type Entry = { ap: number; tp: number }
  const simMap = new Map<string, Map<string, Entry>>()

  for (const round of sim.rounds) {
    for (const team of round.teams) {
      if (!simMap.has(team.team_id)) simMap.set(team.team_id, new Map())
      simMap.get(team.team_id)!.set(round.round, {
        ap: team.advance_prob,
        tp: team.title_prob,
      })
    }
  }

  // teamData: build a BracketTeam for `name` as it appears in `displayRound`
  // advanceProb = P(reaching the round AFTER displayRound) = sim[NEXT[displayRound]].ap
  function teamData(name: string, displayRound: string, isProjected: boolean): BracketTeam {
    const nextRound = NEXT[displayRound]
    const nextEntry = nextRound ? simMap.get(name)?.get(nextRound) : undefined
    const wEntry = simMap.get(name)?.get("W")
    return {
      name,
      advanceProb: nextEntry?.ap ?? 0,
      titleProb: wEntry?.tp ?? 0,
      isProjected,
    }
  }

  // projectWinner: from a BracketSlot, pick the team more likely to reach `targetRound`
  function projectWinner(slot: BracketSlot, targetRound: string): string {
    const topProb = simMap.get(slot.top.name)?.get(targetRound)?.ap ?? 0
    const botProb = simMap.get(slot.bottom.name)?.get(targetRound)?.ap ?? 0
    return topProb >= botProb ? slot.top.name : slot.bottom.name
  }

  // R32: actual ESPN fixture pairings
  const r32Slots: BracketSlot[] = r32.matches.map(m => ({
    top:    teamData(m.home.name, "R32", false),
    bottom: teamData(m.away.name, "R32", false),
  }))

  const rounds: BracketRound[] = [
    { code: "R32", label: ROUND_LABELS["R32"], slots: r32Slots },
  ]

  // R16 → F: project by pairing consecutive slots from the previous round
  const futureCodes = ["R16", "QF", "SF", "F"] as const
  let prevSlots = r32Slots

  for (const code of futureCodes) {
    const nextSlots: BracketSlot[] = []
    for (let i = 0; i + 1 < prevSlots.length; i += 2) {
      const slotA = prevSlots[i]      // feeds top of this new slot
      const slotB = prevSlots[i + 1]  // feeds bottom of this new slot
      const winnerA = projectWinner(slotA, code)
      const winnerB = projectWinner(slotB, code)
      nextSlots.push({
        top:    teamData(winnerA, code, true),
        bottom: teamData(winnerB, code, true),
      })
    }
    rounds.push({ code, label: ROUND_LABELS[code], slots: nextSlots })
    prevSlots = nextSlots
  }

  // Champion: top team in the W round (sorted advance_prob DESC = title_prob DESC)
  const wRound = sim.rounds.find(r => r.round === "W")
  const champTeam = wRound?.teams[0]
  const champion: BracketTeam | null = champTeam
    ? {
        name:         champTeam.team_id,
        advanceProb:  champTeam.title_prob,
        titleProb:    champTeam.title_prob,
        isProjected:  true,
      }
    : null

  return { rounds, champion, runDate: sim.run_date, nIterations: sim.n_iterations }
}
