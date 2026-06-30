/**
 * POST /api/narratives/[reep_id]
 *
 * OpenRouter proxy — keeps OPENROUTER_API_KEY server-side (never in browser).
 * Mirrors the confidence-gated routing logic from api/routes/narratives.py:
 *   confidence_score >= 0.7  → Data Analyst voice (cites Bayesian metrics)
 *   confidence_score < 0.7   → Traditional Scout voice (qualitative only)
 *
 * Player data is read from the static players.json exported nightly by
 * etl/export_json.py so no FastAPI server is needed in production.
 */
import { readFileSync } from "fs"
import path from "path"
import { NextRequest, NextResponse } from "next/server"
import type { PlayerResponse } from "@/lib/api"

const CONFIDENCE_THRESHOLD = 0.7

const _ANTI_YAPPING =
  "\n\nCRITICAL FORMATTING RULE: Do NOT output your chain of thought, reasoning process, " +
  "or internal monologue. Output ONLY the final scouting report in 2-3 concise paragraphs. " +
  "Do not use introductory filler like 'Here is the scouting report' or 'Based on the data'. " +
  "Just start the analysis directly with the player's name or tactical role."

const _JARGON_BAN =
  "\n\nSTRICT LANGUAGE RULE: Never use these words: 'posterior', 'HDI', 'Bayesian', " +
  "'shrinkage', 'percentile rank', 'confidence score', 'prior', 'credible interval'. " +
  "Write as a football analyst speaks on TV — for someone who watches games but " +
  "does not read academic papers."

const DATA_ANALYST_SYSTEM =
  "You are an elite football scout covering FIFA World Cup 2026. " +
  "Write a concise tactical scouting report in 3–4 short paragraphs. " +
  "Cite the specific numbers provided to explain the player's strengths, weaknesses, " +
  "and role in plain football language. Be direct and professional. " +
  "Do not invent any statistics not given to you." +
  _ANTI_YAPPING +
  _JARGON_BAN

const TRADITIONAL_SCOUT_SYSTEM =
  "You are a traditional football scout covering FIFA World Cup 2026. " +
  "Match data for this player is limited — write an impressionistic scouting report " +
  "in 2–3 short paragraphs based on their position and playing style. " +
  "YOU ARE STRICTLY FORBIDDEN from inventing, hallucinating, or mentioning specific " +
  "statistical numbers, xG values, or ratings not explicitly provided. " +
  "Focus on their tactical role and positional characteristics." +
  _ANTI_YAPPING +
  _JARGON_BAN

function buildUserMessage(p: PlayerResponse, highConfidence: boolean): string {
  const name        = p.name ?? p.reep_id
  const nat         = p.nationality ?? "nationality unknown"
  const position    = p.position_detail ?? p.position_macro ?? "Unknown position"
  const archetype   = p.cluster_label ?? position
  const wcPct       = Math.round((1.0 - p.shrinkage_weight) * 100)
  const clubPct     = 100 - wcPct
  const pctRankTop  = Math.max(1, Math.round((1 - p.percentile_rank) * 100))
  const hdiLow      = p.hdi_low.toFixed(2)
  const hdiHigh     = p.hdi_high.toFixed(2)

  if (highConfidence) {
    return (
      `Generate a tactical scouting report for ${name} (${nat}).\n\n` +
      `Position: ${position}\n` +
      `Playing style: ${archetype}\n\n` +
      `Performance data:\n` +
      `- Overall rating: ${p.posterior_mean.toFixed(2)} out of 10` +
      ` — ranks in the top ${pctRankTop}% of ${position.toLowerCase()}s at this tournament\n` +
      `- Rating likely between ${hdiLow} and ${hdiHigh} (accounting for match sample size)\n` +
      `- ${clubPct}% of rating comes from club form (last 2 seasons);` +
      ` ${wcPct}% from this World Cup\n` +
      `- Played ${Math.round(p.wc_minutes)} minutes at this World Cup\n`
    )
  }
  return (
    `Write a scouting report for ${name} (${nat}).\n\n` +
    `Position: ${position}\n` +
    `Playing style: ${archetype}\n` +
    `World Cup minutes: ${Math.round(p.wc_minutes)}\n` +
    `Note: Limited match data — describe their typical tactical role and` +
    ` positional characteristics only.`
  )
}

export async function POST(
  _req: NextRequest,
  { params }: { params: Promise<{ reep_id: string }> }
) {
  const { reep_id } = await params

  // ── Load player from static JSON ─────────────────────────────────────────
  let player: PlayerResponse | undefined
  try {
    const filePath = path.join(process.cwd(), "public", "data", "players.json")
    const players  = JSON.parse(readFileSync(filePath, "utf-8")) as PlayerResponse[]
    player         = players.find((p) => p.reep_id === reep_id)
  } catch (err) {
    console.error("[narratives] Failed to load players.json for", reep_id, err)
    return NextResponse.json(
      { error: "Player data unavailable" },
      { status: 503 }
    )
  }

  if (!player) {
    return NextResponse.json({ error: "Player not found" }, { status: 404 })
  }

  // ── API key check ─────────────────────────────────────────────────────────
  const apiKey = process.env.OPENROUTER_API_KEY
  if (!apiKey) {
    console.error("[narratives] OPENROUTER_API_KEY is not set")
    return NextResponse.json(
      { error: "AI service not configured (missing API key)" },
      { status: 503 }
    )
  }

  const highConfidence = player.confidence_score >= CONFIDENCE_THRESHOLD
  const voice          = highConfidence ? "data_analyst" : "traditional_scout"
  const systemPrompt   = highConfidence ? DATA_ANALYST_SYSTEM : TRADITIONAL_SCOUT_SYSTEM
  const userMessage    = buildUserMessage(player, highConfidence)
  const model = process.env.OPENROUTER_MODEL ?? "google/gemma-4-31b-it:free"

  // ── Call OpenRouter ───────────────────────────────────────────────────────
  let resp: Response
  try {
    resp = await fetch("https://openrouter.ai/api/v1/chat/completions", {
      method: "POST",
      headers: {
        Authorization:  `Bearer ${apiKey}`,
        "Content-Type": "application/json",
        "HTTP-Referer": "https://truescout.vercel.app",
        "X-Title":      "TrueScout WC 2026",
      },
      body: JSON.stringify({
        model,
        messages: [
          { role: "system", content: systemPrompt },
          { role: "user",   content: userMessage  },
        ],
        max_tokens:  450,
        temperature: 0.7,
      }),
      signal: AbortSignal.timeout(25_000),
    })
  } catch (err) {
    const reason = err instanceof Error ? err.message : "Network error"
    console.error("[narratives] OpenRouter request failed for", reep_id, reason)
    return NextResponse.json({ error: reason }, { status: 502 })
  }

  if (!resp.ok) {
    let reason = `OpenRouter returned ${resp.status}`
    try {
      const errBody = await resp.json() as { error?: { message?: string } }
      if (errBody?.error?.message) reason = errBody.error.message
    } catch { /* ignore JSON parse failure */ }
    console.error("[narratives] OpenRouter error for", reep_id, resp.status, reason)
    return NextResponse.json({ error: reason }, { status: 502 })
  }

  const data      = (await resp.json()) as { choices?: { message?: { content?: string } }[] }
  const narrative = data.choices?.[0]?.message?.content?.trim()
  if (!narrative) {
    console.error("[narratives] OpenRouter returned empty content for", reep_id)
    return NextResponse.json({ error: "OpenRouter returned empty response" }, { status: 502 })
  }

  return NextResponse.json({ narrative, voice })
}
