import type { SimulationsResponse, MatchupsResponse, BracketSlotEntry } from "./api"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface BracketTeam {
  name: string
  advanceProb: number   // P(advance FROM this round to next) — drives the prob bar
  titleProb: number     // P(win tournament) — secondary display
  isProjected: boolean  // false only for R32 (actual ESPN fixtures)
  slotProb?: number     // P(this team wins this specific match slot) — from joint distribution
}

export interface BracketSlotAlt {
  team: string
  prob: number
}

export interface BracketSlot {
  top: BracketTeam
  bottom: BracketTeam
  alts: BracketSlotAlt[]   // other teams with non-trivial P(win this slot)
}

export interface BracketRound {
  code: string    // "R32" | "R16" | "QF" | "SF" | "F"
  label: string
  slots: BracketSlot[]
  chaosScore: number  // 0–1: average match entropy (0 = all one-sided; 1 = all 50/50)
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
  r16?: MatchupsResponse,
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

  // Build joint slot-winner lookup: "R32:0", "R16:3", etc. → BracketSlotEntry
  // Only present after the PR4 pipeline has run; falls back to marginal probs.
  const slotMap = new Map<string, BracketSlotEntry>()
  for (const entry of sim.bracket_slots ?? []) {
    slotMap.set(`${entry.round}:${entry.slot_idx}`, entry)
  }

  // R16 team set — used to resolve FT-Pens R32 winners (the advancing team
  // definitionally appears in the next round's fixture list).
  const r16TeamNames = new Set(
    (r16?.matches ?? []).flatMap((m) => [m.home.name, m.away.name]),
  )

  // actualR32Winners: slot_idx → confirmed winning team name (completed matches only)
  // confirmedWinners: set of teams known to have advanced (not projected)
  const actualR32Winners = new Map<number, string>()
  const confirmedWinners = new Set<string>()

  // Binary entropy: measures uncertainty of a single match (0 = certain, 1 = 50/50)
  function binEntropy(p: number): number {
    if (p <= 0 || p >= 1) return 0
    const q = 1 - p
    return -(p * Math.log2(p) + q * Math.log2(q))
  }

  // chaosScore: average binary entropy of top.prob across all slots in a round
  function roundChaos(slots: BracketSlot[]): number {
    if (!slots.length) return 0
    const sum = slots.reduce((acc, s) => acc + binEntropy(s.top.slotProb ?? 0.5), 0)
    return sum / slots.length
  }

  // teamData: build a BracketTeam for `name` as it appears in `displayRound`
  function teamData(
    name: string,
    displayRound: string,
    isProjected: boolean,
    slotProb?: number,
  ): BracketTeam {
    const nextRound = NEXT[displayRound]
    const nextEntry = nextRound ? simMap.get(name)?.get(nextRound) : undefined
    const wEntry = simMap.get(name)?.get("W")
    return {
      name,
      advanceProb: nextEntry?.ap ?? 0,
      titleProb: wEntry?.tp ?? 0,
      isProjected,
      slotProb,
    }
  }

  // resolveSlotWinner: pick the most likely winner of (round, slotIdx).
  // For completed R32 matches the actual result always wins over simulation.
  function resolveSlotWinner(
    round: string,
    slotIdx: number,
    teamA: string,
    teamB: string,
    targetRound: string,
  ): string {
    // Task 1+2: actual R32 results take priority over simulation
    if (round === "R32") {
      const actual = actualR32Winners.get(slotIdx)
      if (actual) return actual === teamA ? teamA : teamB
    }
    // Joint distribution from simulation
    const entry = slotMap.get(`${round}:${slotIdx}`)
    if (entry) {
      const top = entry.top.team
      if (top === teamA || top === teamB) return top
    }
    // Fallback: marginal advance probabilities
    const pA = simMap.get(teamA)?.get(targetRound)?.ap ?? 0
    const pB = simMap.get(teamB)?.get(targetRound)?.ap ?? 0
    return pA >= pB ? teamA : teamB
  }

  // slotProbFor: look up P(team wins round:slotIdx) from joint distribution
  function slotProbFor(round: string, slotIdx: number, team: string): number | undefined {
    const entry = slotMap.get(`${round}:${slotIdx}`)
    if (!entry) return undefined
    if (entry.top.team === team) return entry.top.prob
    const alt = entry.alt.find(a => a.team === team)
    return alt?.prob
  }

  // R32: actual ESPN fixture pairings (slot_idx = match index = array position).
  // For completed matches, winner goes on top and is added to confirmedWinners.
  // FT-Pens winner resolved via R16 fixture list (Task 2).
  const r32Slots: BracketSlot[] = r32.matches.map((m, j) => {
    const entry = slotMap.get(`R32:${j}`)

    let actualWinner: string | null = null
    if (m.is_completed && m.home.score !== null && m.away.score !== null) {
      if (m.home.score > m.away.score) {
        actualWinner = m.home.name
      } else if (m.away.score > m.home.score) {
        actualWinner = m.away.name
      } else {
        // Equal score → FT-Pens: whoever appears in R16 fixtures is the winner
        if (r16TeamNames.has(m.home.name)) actualWinner = m.home.name
        else if (r16TeamNames.has(m.away.name)) actualWinner = m.away.name
      }
    }
    if (actualWinner) {
      actualR32Winners.set(j, actualWinner)
      confirmedWinners.add(actualWinner)
    }

    const topName = actualWinner ?? m.home.name
    const botName = actualWinner
      ? (actualWinner === m.home.name ? m.away.name : m.home.name)
      : m.away.name

    return {
      top:    teamData(topName, "R32", false, slotProbFor("R32", j, topName)),
      bottom: teamData(botName, "R32", false, slotProbFor("R32", j, botName)),
      alts:   entry?.alt.filter(a => a.team !== topName && a.team !== botName) ?? [],
    }
  })

  const rounds: BracketRound[] = [
    {
      code:       "R32",
      label:      ROUND_LABELS["R32"],
      slots:      r32Slots,
      chaosScore: roundChaos(r32Slots),
    },
  ]

  // R16 → F: project by pairing slots from the previous round.
  // sim.pairings[code] contains the correct slot indices to pair — critical for R16
  // where ESPN chronological order ≠ bracket pairing order.
  // Falls back to sequential pairing when pairings are absent (old data / backward compat).
  const futureCodes = ["R16", "QF", "SF", "F"] as const
  let prevSlots = r32Slots
  let prevCode  = "R32"

  for (const code of futureCodes) {
    const nextSlots: BracketSlot[] = []
    const codePairings = sim.pairings?.[code]
    const nSlots = prevSlots.length / 2

    for (let newSlotIdx = 0; newSlotIdx < nSlots; newSlotIdx++) {
      // Use pairings when available; fall back to sequential (old behaviour)
      const [slotA, slotB] = codePairings?.[newSlotIdx] ?? [2 * newSlotIdx, 2 * newSlotIdx + 1]

      // Who comes out of the two prevSlots (winners of prev round matches)?
      const teamA = resolveSlotWinner(prevCode, slotA, prevSlots[slotA].top.name, prevSlots[slotA].bottom.name, code)
      const teamB = resolveSlotWinner(prevCode, slotB, prevSlots[slotB].top.name, prevSlots[slotB].bottom.name, code)

      // Who wins the code:newSlotIdx match?
      const slotEntry     = slotMap.get(`${code}:${newSlotIdx}`)
      const matchWinner   = resolveSlotWinner(code, newSlotIdx, teamA, teamB, NEXT[code] ?? "W")
      const matchLoser    = matchWinner === teamA ? teamB : teamA
      const altsFromEntry = slotEntry?.alt.filter(a => a.team !== teamA && a.team !== teamB) ?? []

      // A team confirmed via a completed R32 result is not "projected" even in R16
      const winnerConfirmed = confirmedWinners.has(matchWinner)
      const loserConfirmed  = confirmedWinners.has(matchLoser)
      nextSlots.push({
        top:    teamData(matchWinner, code, !winnerConfirmed, slotProbFor(code, newSlotIdx, matchWinner)),
        bottom: teamData(matchLoser,  code, !loserConfirmed,  slotProbFor(code, newSlotIdx, matchLoser)),
        alts:   altsFromEntry,
      })
    }

    rounds.push({
      code,
      label:      ROUND_LABELS[code],
      slots:      nextSlots,
      chaosScore: roundChaos(nextSlots),
    })
    prevSlots = nextSlots
    prevCode  = code
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
