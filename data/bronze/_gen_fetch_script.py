"""Generate sofascore_browser_fetch.js with embedded player ID lists."""
import json
from pathlib import Path

targets = json.loads(Path("data/bronze/_fetch_targets.json").read_text())
mv_targets = targets["mv_targets"]
cs_targets = targets["club_stat_targets"]

mv_json = json.dumps(mv_targets)
cs_json = json.dumps(cs_targets)

XCAPTCHA = (
    "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9"
    ".eyJleHAiOjE3ODMxMDg4NTcsImlwIjoiMTA3LjE5My4xNDAuMTk3IiwiZiI6ImE3YWQzMCJ9"
    "._sRUPr2hLYpm4K02rSEcuC5UyIeSmHUTZE8JLalpZEk"
)
XRW = "b7664a"  # x-requested-with (rotates with each token)

HDRS = (
    "{ 'accept': '*/*', 'x-requested-with': '" + XRW + "', 'x-captcha': XCAPTCHA }"
)

js = (
    "// ============================================================\n"
    "// TrueScout — Sofascore club stats fetch (CS only — MV already done)\n"
    "// Paste in DevTools console on www.sofascore.com\n"
    "// Token expires ~1h from capture — run immediately.\n"
    "// Downloads club_stats_results.json (~7 min for 673 players).\n"
    "// ============================================================\n"
    "\n"
    "const CS_TARGETS = " + cs_json + ";\n"
    "const DELAY_MS   = 650;\n"
    "const XCAPTCHA   = '" + XCAPTCHA + "';\n"
    "const HDRS       = " + HDRS + ";\n"
    "\n"
    "function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }\n"
    "function downloadJson(obj, fn) {\n"
    "  const b = new Blob([JSON.stringify(obj)], {type:'application/json'});\n"
    "  const u = URL.createObjectURL(b);\n"
    "  const a = document.createElement('a');\n"
    "  a.href=u; a.download=fn; a.click();\n"
    "  setTimeout(()=>URL.revokeObjectURL(u), 5000);\n"
    "}\n"
    "\n"
    "function extractSeasons(data) {\n"
    "  // Actual API structure: {uniqueTournamentSeasons: [{uniqueTournament, seasons:[...]}, ...]}\n"
    "  // Each entry is one competition; each has a 'seasons' array of year-buckets.\n"
    "  // Fallback chain for legacy / future API changes:\n"
    "  if (!data) return [];\n"
    "  if (Array.isArray(data.uniqueTournamentSeasons)) return data.uniqueTournamentSeasons;\n"
    "  const s = data.statistics;\n"
    "  if (s && Array.isArray(s.seasons)) return s.seasons;\n"
    "  if (Array.isArray(s))             return s;\n"
    "  if (Array.isArray(data.seasons))  return data.seasons;\n"
    "  return [];\n"
    "}\n"
    "\n"
    "async function probe() {\n"
    "  // Fetch Mohamed Salah (ss=159665) as canary — should have 15+ tournament entries.\n"
    "  console.log('[PROBE] Testing token with Salah (ss=159665)...');\n"
    "  const resp = await fetch('/api/v1/player/159665/statistics/seasons', {headers: HDRS});\n"
    "  const data = await resp.json();\n"
    "  if (data && data.error) {\n"
    "    console.error('[PROBE] Hard 403 — get a fresh x-captcha and re-run.', data.error);\n"
    "    return false;\n"
    "  }\n"
    "  const seasons = extractSeasons(data);\n"
    "  if (seasons.length === 0) {\n"
    "    console.error('[PROBE] Soft-block: Salah returned 0 entries. Raw:', JSON.stringify(data).slice(0,400));\n"
    "    return false;\n"
    "  }\n"
    "  console.log('[PROBE] OK — Salah has', seasons.length, 'tournament entries. Top keys:', Object.keys(seasons[0] || {}));\n"
    "  return true;\n"
    "}\n"
    "\n"
    "async function fetchClubStats() {\n"
    "  const ok = await probe();\n"
    "  if (!ok) return;\n"
    "  await sleep(700);\n"
    "\n"
    "  console.log('[CS] Fetching club stats for ' + CS_TARGETS.length + ' players...');\n"
    "  const results = {};\n"
    "  for (let i = 0; i < CS_TARGETS.length; i++) {\n"
    "    const [reepId, ssId] = CS_TARGETS[i];\n"
    "    try {\n"
    "      const resp = await fetch('/api/v1/player/' + ssId + '/statistics/seasons', {headers: HDRS});\n"
    "      const data = await resp.json();\n"
    "      if (data && data.error) {\n"
    "        results[reepId] = { ss_id: ssId, error: data.error };\n"
    "        if (data.error.code === 403) { console.error('[CS] 403 — aborting'); break; }\n"
    "      } else {\n"
    "        const uts = extractSeasons(data);\n"
    "        results[reepId] = { ss_id: ssId, uniqueTournamentSeasons: uts };\n"
    "        if (i < 5 && uts.length === 0) {\n"
    "          console.warn('[CS] Warning: player', ssId, 'returned 0 entries');\n"
    "        }\n"
    "      }\n"
    "    } catch(e) {\n"
    "      results[reepId] = { ss_id: ssId, error: String(e) };\n"
    "    }\n"
    "    if ((i + 1) % 100 === 0) console.log('[CS] ' + (i+1) + '/' + CS_TARGETS.length);\n"
    "    await sleep(DELAY_MS);\n"
    "  }\n"
    "  console.log('[CS] Done (' + Object.keys(results).length + ' entries) — downloading...');\n"
    "  downloadJson(results, 'club_stats_results.json');\n"
    "}\n"
    "\n"
    "fetchClubStats();\n"
)

out = Path("data/bronze/sofascore_browser_fetch.js")
out.write_text(js, encoding="utf-8")
size_kb = out.stat().st_size / 1024
print(f"Written: {out}  ({size_kb:.1f} KB)")
print(f"Club stat targets: {len(cs_targets)}")
est = len(cs_targets) * 0.65 / 60
print(f"Estimated runtime: ~{est:.0f} min")
