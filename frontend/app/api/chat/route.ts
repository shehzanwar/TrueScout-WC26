/**
 * POST /api/chat
 *
 * TrueScout AI chat assistant — answers questions about WC 2026 using
 * tournament data from chat_index.json and the Gemini API.
 *
 * Body: { message: string; history?: { role: "user"|"model"; text: string }[] }
 * Response: { reply: string }
 */
import { readFileSync } from "fs"
import path from "path"
import { NextRequest, NextResponse } from "next/server"

export const runtime = "nodejs"
export const maxDuration = 60
export const dynamic = "force-dynamic"

const GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
const PRIMARY_MODEL = process.env.GOOGLE_AI_MODEL ?? "gemini-2.5-flash"
const MODELS = [PRIMARY_MODEL, "gemini-2.0-flash"].filter((m, i, a) => a.indexOf(m) === i)

// ── Chat index cache ─────────────────────────────────────────────────────────
let _indexCache: Record<string, unknown> | null = null
function getChatIndex(): Record<string, unknown> {
  if (!_indexCache) {
    const p = path.join(process.cwd(), "public", "data", "chat_index.json")
    try {
      _indexCache = JSON.parse(readFileSync(p, "utf-8"))
    } catch {
      _indexCache = {}
    }
  }
  return _indexCache!
}

function buildSystemPrompt(index: Record<string, unknown>): string {
  const stage    = index.current_stage ?? "the tournament"
  const runDate  = index.run_date ?? "recent"

  const teamsArr = (index.champion_probs as { team: string; prob_pct: number }[] | undefined) ?? []
  const teamsStr = teamsArr
    .map(t => `${t.team} ${t.prob_pct}%`)
    .join(", ")

  const scorersArr = (index.top_scorers as { name: string; team: string; goals: number }[] | undefined) ?? []
  const scorersStr = scorersArr.map(s => `${s.name} (${s.team}) ${s.goals}G`).join(", ")

  const upcoming = (index.upcoming_matches as { round: string; date: string; home: string; away: string; home_win_prob?: number }[] | undefined) ?? []
  const upcomingStr = upcoming
    .map(m => {
      const prob = m.home_win_prob != null ? ` (${m.home_win_prob}% home)` : ""
      return `${m.home} vs ${m.away}${prob} [${m.round}, ${m.date}]`
    })
    .join("; ")

  const recent = (index.recent_results as { home: string; away: string; score: string; round: string }[] | undefined) ?? []
  const recentStr = recent.map(r => `${r.home} ${r.score} ${r.away} (${r.round})`).join("; ")

  const awards = (index.awards as Record<string, { name: string; team: string; goals?: number; saves?: number; rating?: number }> | undefined) ?? {}
  const awardsLines = [
    awards.golden_boot ? `Golden Boot: ${awards.golden_boot.name} (${awards.golden_boot.team}) ${awards.golden_boot.goals}G` : null,
    awards.golden_glove ? `Golden Glove: ${awards.golden_glove.name} (${awards.golden_glove.team}) ${awards.golden_glove.saves} saves` : null,
    awards.golden_ball_leader ? `Golden Ball leader: ${awards.golden_ball_leader.name} (${awards.golden_ball_leader.team}) rating ${awards.golden_ball_leader.rating}` : null,
  ].filter(Boolean).join("; ")

  return [
    `You are TrueScout, an AI football analyst for the 2026 FIFA World Cup.`,
    `Today is ${runDate}. The tournament is currently at: ${stage}.`,
    ``,
    `TOURNAMENT DATA (model run ${runDate}):`,
    `Title probabilities: ${teamsStr || "data unavailable"}`,
    `Top scorers: ${scorersStr || "none yet"}`,
    `Upcoming matches: ${upcomingStr || "none scheduled"}`,
    `Recent results: ${recentStr || "none yet"}`,
    awardsLines ? `Award leaders: ${awardsLines}` : "",
    ``,
    `RULES:`,
    `- Answer in 2-4 sentences unless the user asks for detail.`,
    `- Cite specific probabilities and stats when relevant.`,
    `- Say "the model shows" or "simulations suggest" when citing probabilities — not "I predict".`,
    `- If you don't know something, say so rather than guessing.`,
    `- Never mention "posterior", "Bayesian", "shrinkage", or other technical model terms.`,
    `- Write like a knowledgeable football analyst, not an academic.`,
  ].filter(s => s !== "").join("\n")
}

function stripReasoningTags(text: string): string {
  return text
    .replace(/<think>[\s\S]*?<\/think>/gi, "")
    .replace(/<reasoning>[\s\S]*?<\/reasoning>/gi, "")
    .trim()
}

interface HistoryMessage { role: "user" | "model"; text: string }

export async function POST(req: NextRequest) {
  const apiKey = process.env.GOOGLE_AI_API_KEY
  if (!apiKey) {
    return NextResponse.json({ error: "AI service not configured" }, { status: 503 })
  }

  let message: string
  let history: HistoryMessage[] = []
  try {
    const body = await req.json() as { message?: string; history?: HistoryMessage[] }
    message = (body.message ?? "").trim()
    history = body.history ?? []
  } catch {
    return NextResponse.json({ error: "Invalid request body" }, { status: 400 })
  }

  if (!message) {
    return NextResponse.json({ error: "message is required" }, { status: 400 })
  }

  const index = getChatIndex()
  const systemPrompt = buildSystemPrompt(index)

  // Build conversation contents: history + current message
  const contents = [
    ...history.map(m => ({
      role: m.role,
      parts: [{ text: m.text }],
    })),
    { role: "user", parts: [{ text: message }] },
  ]

  async function callModel(model: string): Promise<{ reply: string; model: string } | { error: string; status: number; retryAfterMs?: number }> {
    const url = `${GEMINI_BASE}/${model}:generateContent?key=${apiKey}`
    let resp: Response
    try {
      resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          system_instruction: { parts: [{ text: systemPrompt }] },
          contents,
          generationConfig: { maxOutputTokens: 512, temperature: 0.5 },
        }),
        signal: AbortSignal.timeout(45_000),
      })
    } catch (err) {
      return { error: err instanceof Error ? err.message : "Network error", status: 503 }
    }

    if (resp.status === 429 || resp.status === 503) {
      let retryAfterMs: number | undefined
      try {
        const e = await resp.json() as { error?: { message?: string } }
        const msg = e?.error?.message ?? ""
        const match = msg.match(/retry in ([\d.]+)s/i)
        if (match) retryAfterMs = Math.ceil(parseFloat(match[1]) * 1000)
      } catch { /* ignore */ }
      return { error: "rate_limited", status: resp.status, retryAfterMs }
    }

    if (!resp.ok) {
      return { error: `Gemini ${resp.status}`, status: resp.status }
    }

    const data = await resp.json() as { candidates?: { content?: { parts?: { text?: string }[] } }[] }
    const raw = data.candidates?.[0]?.content?.parts?.[0]?.text?.trim()
    if (!raw) return { error: "empty response", status: 502 }

    const reply = stripReasoningTags(raw)
    if (!reply) return { error: "reasoning-only response", status: 502 }

    return { reply, model }
  }

  for (const model of MODELS) {
    const result = await callModel(model)
    if ("reply" in result) return NextResponse.json({ reply: result.reply, model: result.model })

    // On rate limit: wait the suggested delay (capped at 60s) then retry once
    if (result.error === "rate_limited" && result.retryAfterMs) {
      const delay = Math.min(result.retryAfterMs, 60_000)
      await new Promise(r => setTimeout(r, delay))
      const retry = await callModel(model)
      if ("reply" in retry) return NextResponse.json({ reply: retry.reply, model: retry.model })
    }
  }

  return NextResponse.json(
    { error: "The AI assistant is temporarily busy — try again in a moment." },
    { status: 503 }
  )
}
