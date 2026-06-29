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
const FALLBACK_NARRATIVE =
  "Scouting report temporarily unavailable. The AI narrative service could not be reached. Please try again later."

const _ANTI_YAPPING =
  "\n\nCRITICAL FORMATTING RULE: Do NOT output your chain of thought, reasoning process, " +
  "or internal monologue. Output ONLY the final scouting report in 2-3 concise paragraphs. " +
  "Do not use introductory filler like 'Here is the scouting report' or 'Based on the data'. " +
  "Just start the analysis directly with the player's name or tactical role."

const DATA_ANALYST_SYSTEM =
  "You are an elite Data Analyst scout for FIFA World Cup 2026. " +
  "Write a concise tactical scouting report in 3–4 short paragraphs. " +
  "Base your evaluation STRICTLY on the provided Bayesian metrics — cite the specific " +
  "numbers to explain the player's strengths, weaknesses, and role. " +
  "Be direct, professional, and data-driven. Do not invent any statistics not provided." +
  _ANTI_YAPPING

const TRADITIONAL_SCOUT_SYSTEM =
  "You are a Traditional Scout for FIFA World Cup 2026. " +
  "The quantitative data for this player is sparse or low-confidence. " +
  "Write an impressionistic scouting report in 2–3 short paragraphs based on their " +
  "position and archetype cluster. " +
  "YOU ARE STRICTLY FORBIDDEN from inventing, hallucinating, or mentioning specific " +
  "statistical numbers, xG values, percentiles, or ratings not explicitly provided. " +
  "Focus on their typical tactical role and archetypal positional characteristics." +
  _ANTI_YAPPING

function buildUserMessage(p: PlayerResponse, highConfidence: boolean): string {
  const name          = p.name ?? p.reep_id
  const nat           = p.nationality ?? "nationality unknown"
  const position      = p.position_detail ?? p.position_macro ?? "Unknown position"
  const archetype     = p.cluster_label ?? `Cluster ${p.cluster_id}`
  const wcWeightPct   = ((1.0 - p.shrinkage_weight) * 100).toFixed(0)

  if (highConfidence) {
    return (
      `Generate a tactical scouting report for ${name} (${nat}).\n\n` +
      `Position: ${position}\n` +
      `Archetype: ${archetype}\n\n` +
      `Bayesian Posterior Metrics:\n` +
      `- Overall rating: ${p.posterior_mean.toFixed(3)}` +
      ` (p${(p.percentile_rank * 100).toFixed(0)} within position group)\n` +
      `- 90% HDI: ${p.hdi_low.toFixed(3)} – ${p.hdi_high.toFixed(3)}` +
      `  (uncertainty: ±${p.posterior_std.toFixed(3)})\n` +
      `- Club prior rating: ${p.prior_mean.toFixed(3)}` +
      ` — weighted ${(p.shrinkage_weight * 100).toFixed(0)}% of posterior\n` +
      `- World Cup data contribution: ${wcWeightPct}% of posterior` +
      ` (${p.wc_minutes.toFixed(0)} minutes played)\n` +
      `- Confidence score: ${p.confidence_score.toFixed(2)}/1.00\n`
    )
  }
  return (
    `Write a scouting report for ${name} (${nat}).\n\n` +
    `Position: ${position}\n` +
    `Archetype: ${archetype}\n` +
    `World Cup minutes: ${p.wc_minutes.toFixed(0)}\n` +
    `Data note: Limited match data (confidence ${p.confidence_score.toFixed(2)}/1.00).\n` +
    `Describe their typical tactical role and positional characteristics only.`
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
  } catch {
    return NextResponse.json(
      { narrative: FALLBACK_NARRATIVE, voice: "traditional_scout" },
      { status: 200 }
    )
  }

  if (!player) {
    return NextResponse.json({ error: "Player not found" }, { status: 404 })
  }

  // ── API key check ─────────────────────────────────────────────────────────
  const apiKey = process.env.OPENROUTER_API_KEY
  if (!apiKey) {
    return NextResponse.json(
      { narrative: FALLBACK_NARRATIVE, voice: "traditional_scout" },
      { status: 200 }
    )
  }

  const highConfidence = player.confidence_score >= CONFIDENCE_THRESHOLD
  const voice          = highConfidence ? "data_analyst" : "traditional_scout"
  const systemPrompt   = highConfidence ? DATA_ANALYST_SYSTEM : TRADITIONAL_SCOUT_SYSTEM
  const userMessage    = buildUserMessage(player, highConfidence)
  const model          = process.env.OPENROUTER_MODEL ?? "google/gemma-3-27b-it:free"

  // ── Call OpenRouter ───────────────────────────────────────────────────────
  try {
    const resp = await fetch("https://openrouter.ai/api/v1/chat/completions", {
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

    if (!resp.ok) {
      throw new Error(`OpenRouter ${resp.status}`)
    }

    const data      = (await resp.json()) as { choices?: { message?: { content?: string } }[] }
    const narrative = data.choices?.[0]?.message?.content?.trim() ?? FALLBACK_NARRATIVE

    return NextResponse.json({ narrative, voice })
  } catch (err) {
    console.error("[narratives] OpenRouter call failed for", reep_id, err)
    return NextResponse.json(
      { narrative: FALLBACK_NARRATIVE, voice },
      { status: 200 }
    )
  }
}
