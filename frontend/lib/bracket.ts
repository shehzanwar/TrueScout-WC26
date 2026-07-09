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
  preMatchProb?: number // pre-completion slotProb; preserved on R32 completed slots for chaos
}

export interface BracketSlotAlt {
  team: string
  prob: number
}

export interface BracketSlot {
  top: BracketTeam
  bottom: BracketTeam
  alts: BracketSlotAlt[]   // other teams with non-trivial P(win this slot)
  isCompleted?: boolean     // true when R32 match has a confirmed final result
  score?: string            // "2-1" (winner score first) when isCompleted
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

  // Linear competitiveness: 1.0 = pure coin flip (50/50), 0.0 = certain outcome (100/0).
  // Better than binary entropy because 70/30 reads as 0.60 ("moderate favourite"), not 0.88
  // ("almost maximum chaos"). Matches how fans intuitively perceive match competitiveness.
  function competitiveness(p: number): number {
    if (p <= 0 || p >= 1) return 0
    return 1 - Math.abs(2 * p - 1)
  }

  // chaosScore: average match competitiveness across all slots in the round.
  // For pending slots: uses current slotProb (simulation probability).
  // For completed slots: uses preMatchProb (probability locked in before kickoff),
  //   so the score reflects how unpredictable the round WAS, not how many matches remain.
  // If a round has no data at all, returns 0.
  function roundChaos(slots: BracketSlot[]): number {
    const probs = slots.map(s => {
      if (s.isCompleted) return s.top.preMatchProb ?? null  // use pre-kick prob for graded matches
      return s.top.slotProb ?? null                        // use simulation prob for pending
    }).filter((p): p is number => p !== null)
    if (!probs.length) return 0
    return probs.reduce((acc, p) => acc + competitiveness(p), 0) / probs.length
  }

  // teamData: build a BracketTeam for `name` as it appears in `displayRound`
  function teamData(
    name: string,
    displayRound: string,
    isProjected: boolean,
    slotProb?: number,
    preMatchProb?: number,
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
      preMatchProb,
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

  // preMatchProbFor: look up the pre-kickoff BT probability for completed R32 slots.
  // The ETL enriches top.pre_match_prob when the simulation-derived prob == 1.0.
  function preMatchProbFor(slotIdx: number, team: string): number | undefined {
    const entry = slotMap.get(`R32:${slotIdx}`)
    if (entry?.top.team === team) return entry.top.pre_match_prob
    return undefined
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
        // Equal score → FT-Pens: use exported winner (brier_log/manual_winners.json) first,
        // then fall back to R16 cross-reference once those fixtures are published
        if (m.winner) actualWinner = m.winner
        else if (r16TeamNames.has(m.home.name)) actualWinner = m.home.name
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

    // Build score string for completed matches: winner's score first
    let score: string | undefined
    if (actualWinner && m.home.score != null && m.away.score != null) {
      const winnerScore = actualWinner === m.home.name ? m.home.score : m.away.score
      const loserScore  = actualWinner === m.home.name ? m.away.score : m.home.score
      score = `${winnerScore}–${loserScore}`
    }

    // For completed matches: display slotProb as 1.0/0.0 but preserve the pre-kick
    // BT probability (from match_probs table, via ETL enrichment) for chaos scoring.
    const preMatchTop = actualWinner ? preMatchProbFor(j, topName) : undefined
    const topProb     = actualWinner ? 1.0 : (slotProbFor("R32", j, topName) ?? undefined)
    const botProb     = actualWinner ? 0.0 : (slotProbFor("R32", j, botName) ?? undefined)

    return {
      top:         teamData(topName, "R32", false, topProb, preMatchTop),
      bottom:      teamData(botName, "R32", false, botProb),
      alts:        actualWinner ? [] : (entry?.alt.filter(a => a.team !== topName && a.team !== botName) ?? []),
      isCompleted: !!actualWinner,
      score,
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
      let teamA = resolveSlotWinner(prevCode, slotA, prevSlots[slotA].top.name, prevSlots[slotA].bottom.name, code)
      let teamB = resolveSlotWinner(prevCode, slotB, prevSlots[slotB].top.name, prevSlots[slotB].bottom.name, code)

      // R16: ESPN fixtures are the source of truth for team names.
      // "Round of 32 X Winner" placeholders are resolved via actualR32Winners (actual)
      // or prevSlots (projected) so pairings are never needed to get correct teams.
      if (code === "R16" && r16?.matches[newSlotIdx]) {
        const fix = r16.matches[newSlotIdx]
        const resolveName = (raw: string): string | null => {
          if (!raw) return null
          const m = raw.match(/Round of 32 (\d+) Winner/)
          if (m) {
            const r32Idx = parseInt(m[1]) - 1
            return actualR32Winners.get(r32Idx) ?? prevSlots[r32Idx]?.top.name ?? null
          }
          if (raw.includes("Winner") || raw === "TBD") return null
          return raw
        }
        const resolvedA = resolveName(fix.home.name)
        const resolvedB = resolveName(fix.away.name)
        if (resolvedA) teamA = resolvedA
        if (resolvedB) teamB = resolvedB
      }

      // R16 completion: if the ESPN fixture is done, lock in the actual result.
      // Mirrors the R32 logic — prevents completed R16 slots from showing 100%/grayed.
      let r16Done  = false
      let r16Score: string | undefined

      if (code === "R16" && r16?.matches[newSlotIdx]?.is_completed) {
        const fix = r16.matches[newSlotIdx]
        if (fix.home.score != null && fix.away.score != null) {
          let actualWinner: string | null = null
          if      (fix.home.score > fix.away.score) actualWinner = teamA
          else if (fix.away.score > fix.home.score) actualWinner = teamB
          else if (fix.winner)                       actualWinner = fix.winner
          if (actualWinner) {
            confirmedWinners.add(actualWinner)
            r16Done = true
            const ws = actualWinner === teamA ? fix.home.score : fix.away.score
            const ls = actualWinner === teamA ? fix.away.score : fix.home.score
            r16Score = `${ws}–${ls}`
            // Swap so winner is always teamA for the slot builder below
            if (actualWinner === teamB) { const tmp = teamA; teamA = teamB; teamB = tmp }
          }
        }
      }

      // Who wins the code:newSlotIdx match?
      const slotEntry     = slotMap.get(`${code}:${newSlotIdx}`)
      const matchWinner   = r16Done ? teamA : resolveSlotWinner(code, newSlotIdx, teamA, teamB, NEXT[code] ?? "W")
      const matchLoser    = matchWinner === teamA ? teamB : teamA
      const altsFromEntry = slotEntry?.alt.filter(a => a.team !== teamA && a.team !== teamB) ?? []

      // A team confirmed via a completed R32/R16 result is not "projected"
      const winnerConfirmed = confirmedWinners.has(matchWinner)
      const loserConfirmed  = confirmedWinners.has(matchLoser)
      // Save the pre-match BT probability before locking slotProb to 1.0/0.0.
      // roundChaos uses top.preMatchProb on completed slots so the chaos meter reflects
      // how competitive the round WAS (same pattern as R32 via preMatchProbFor).
      const preMatchWinnerProb = r16Done
        ? slotMap.get(`${code}:${newSlotIdx}`)?.top.pre_match_prob
        : undefined
      nextSlots.push({
        top:    teamData(matchWinner, code, !winnerConfirmed, r16Done ? 1.0 : slotProbFor(code, newSlotIdx, matchWinner), preMatchWinnerProb),
        bottom: teamData(matchLoser,  code, !loserConfirmed,  r16Done ? 0.0 : slotProbFor(code, newSlotIdx, matchLoser)),
        alts:   r16Done ? [] : altsFromEntry,
        isCompleted: r16Done || undefined,
        score:       r16Score,
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

  // Reorder R32 slots for correct visual alignment.
  // The Connector component assumes adjacent slot pairs feed the same R16 match,
  // but ESPN chronological order doesn't honour this. Flatten pairings.R16 to get
  // the display order: [pair0_a, pair0_b, pair1_a, pair1_b, ...].
  const r16PairingOrder = sim.pairings?.["R16"]
  if (r16PairingOrder) {
    const displayOrder = r16PairingOrder.flatMap(([a, b]) => [a, b])
    rounds[0] = {
      ...rounds[0],
      slots: displayOrder.map((i) => rounds[0].slots[i]),
    }
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
