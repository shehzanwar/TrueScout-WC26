/**
 * POST /api/narratives/[reep_id]
 *
 * Google AI Studio (Gemini) proxy — keeps GOOGLE_AI_API_KEY server-side.
 * Uses the OpenAI-compatible endpoint so the request shape is unchanged.
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

export const runtime = "nodejs"
export const maxDuration = 60
export const dynamic = "force-dynamic"

const CONFIDENCE_THRESHOLD = 0.7

// Module-level cache — shared within a warm Lambda instance; avoids 4 MB reads per request
let _playersCache: PlayerResponse[] | null = null
function getPlayers(): PlayerResponse[] {
  if (!_playersCache) {
    const filePath = path.join(process.cwd(), "public", "data", "players.json")
    _playersCache = JSON.parse(readFileSync(filePath, "utf-8")) as PlayerResponse[]
  }
  return _playersCache
}

// Google AI Studio OpenAI-compatible endpoint
const GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

// Model chain: 2.0-flash primary, 1.5-flash fallback
const PRIMARY_MODEL  = process.env.GOOGLE_AI_MODEL ?? "gemini-2.0-flash"
const FALLBACK_MODEL = "gemini-1.5-flash"
const MODELS = [...new Set([PRIMARY_MODEL, FALLBACK_MODEL])]

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

function stripReasoningTags(text: string): string {
  return text
    .replace(/<think>[\s\S]*?<\/think>/gi, "")
    .replace(/<reasoning>[\s\S]*?<\/reasoning>/gi, "")
    .trim()
}

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

  // ── Load player from static JSON (module-level cache) ────────────────────
  let player: PlayerResponse | undefined
  try {
    player = getPlayers().find((p) => p.reep_id === reep_id)
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
  const apiKey = process.env.GOOGLE_AI_API_KEY
  if (!apiKey) {
    console.error("[narratives] GOOGLE_AI_API_KEY is not set")
    return NextResponse.json(
      { error: "AI service not configured (missing API key)" },
      { status: 503 }
    )
  }

  const highConfidence = player.confidence_score >= CONFIDENCE_THRESHOLD
  const voice          = highConfidence ? "data_analyst" : "traditional_scout"
  const systemPrompt   = highConfidence ? DATA_ANALYST_SYSTEM : TRADITIONAL_SCOUT_SYSTEM
  const userMessage    = buildUserMessage(player, highConfidence)

  // ── Model chain: gemini-2.0-flash → gemini-1.5-flash ─────────────────────
  let lastError = ""
  for (const model of MODELS) {
    let resp: Response
    try {
      resp = await fetch(GEMINI_ENDPOINT, {
        method: "POST",
        headers: {
          Authorization:  `Bearer ${apiKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model,
          messages: [
            { role: "system", content: systemPrompt },
            { role: "user",   content: userMessage  },
          ],
          max_tokens:  800,
          temperature: 0.7,
        }),
        signal: AbortSignal.timeout(45_000),
      })
    } catch (err) {
      lastError = err instanceof Error ? err.message : "Network error"
      console.warn("[narratives] Model", model, "network error:", lastError)
      continue
    }

    if (!resp.ok) {
      try {
        const errBody = await resp.json() as { error?: { message?: string } }
        lastError = errBody?.error?.message ?? `Gemini returned ${resp.status}`
      } catch { lastError = `Gemini returned ${resp.status}` }
      console.warn("[narratives] Model", model, "returned", resp.status, lastError)
      continue
    }

    const data = (await resp.json()) as { choices?: { message?: { content?: string } }[] }
    const raw  = data.choices?.[0]?.message?.content?.trim()
    if (!raw) {
      lastError = "empty response"
      console.warn("[narratives] Model", model, "returned empty content for", reep_id)
      continue
    }

    const narrative = stripReasoningTags(raw)
    if (!narrative) {
      lastError = "reasoning-only response (no content after stripping think tags)"
      console.warn("[narratives] Model", model, ":", lastError, "for", reep_id)
      continue
    }

    if (model !== MODELS[0]) {
      console.info("[narratives] Fallback model used:", model, "for", reep_id)
    } else {
      console.info("[narratives] Primary model succeeded:", model, "for", reep_id)
    }
    return NextResponse.json({ narrative, voice, model })
  }

  console.error("[narratives] All models failed for", reep_id, "— last error:", lastError)
  return NextResponse.json(
    { error: lastError || "Gemini unavailable" },
    { status: 502 }
  )
}
