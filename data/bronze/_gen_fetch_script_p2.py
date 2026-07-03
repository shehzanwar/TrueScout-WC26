"""
Generate sofascore_browser_fetch_p2.js — Phase 2 club stats fetch.

Endpoint: /player/{ss_id}/unique-tournament/{ut_id}/season/{season_id}/statistics/overall
Targets:  1310 (player × league-season pairs, max 2 per player)
Runtime:  ~15 min
"""
import json
from pathlib import Path

targets = json.loads(
    Path("data/bronze/_fetch_targets_p2.json").read_text(encoding="utf-8")
)["phase2_targets"]

# [reep_id, ss_id, ut_id, season_id, ut_name, year]
targets_json = json.dumps(targets)

XCAPTCHA = (
    "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9"
    ".eyJleHAiOjE3ODMxMTA4MTIsImlwIjoiMTA3LjE5My4xNDAuMTk3IiwiZiI6ImIwZDk3NCJ9"
    ".acn7jZZLGyQIFtbqlPGcpXH5-CozMOGHoy_1YJJkCOs"
)
XRW = "5593e0"

js = """\
// ============================================================
// TrueScout — Phase 2 club stats fetch
// Endpoint: /player/{id}/unique-tournament/{ut_id}/season/{sid}/statistics/overall
// Paste in DevTools console on www.sofascore.com
// Token expires ~1h from capture — run immediately.
// Downloads club_stats_p2_results.json (~15 min).
// ============================================================

const TARGETS  = """ + targets_json + """;
const DELAY_MS = 700;
const XCAPTCHA = '""" + XCAPTCHA + """';
const XRW      = '""" + XRW + """';
const HDRS     = { 'accept': '*/*', 'x-requested-with': XRW, 'x-captcha': XCAPTCHA };

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
function downloadJson(obj, fn) {
  const b = new Blob([JSON.stringify(obj)], {type:'application/json'});
  const u = URL.createObjectURL(b);
  const a = document.createElement('a');
  a.href=u; a.download=fn; a.click();
  setTimeout(()=>URL.revokeObjectURL(u), 5000);
}

async function probe() {
  // Messi (ss=12994) WC 2026 season — same request the browser already made (304 = cache hit = token valid)
  console.log('[PROBE] Verifying token with Messi (ss=12994, ut=16, s=58210)...');
  const resp = await fetch('/api/v1/player/12994/unique-tournament/16/season/58210/statistics/overall', {headers: HDRS});
  const data = await resp.json().catch(() => null);
  if (!data || data.error) {
    console.error('[PROBE] Failed — get a fresh x-captcha and re-run.', data);
    return false;
  }
  const keys = Object.keys(data.statistics || {});
  if (keys.length === 0) {
    console.error('[PROBE] Empty statistics object. Raw:', JSON.stringify(data).slice(0, 300));
    return false;
  }
  console.log('[PROBE] OK — stat keys:', keys.slice(0, 8).join(', '));
  return true;
}

async function run() {
  if (!await probe()) return;
  await sleep(800);

  // Group targets by reep_id so results accumulate per player
  const results = {};
  let fetched = 0, errors = 0;

  for (let i = 0; i < TARGETS.length; i++) {
    const [reepId, ssId, utId, seasonId, utName, year] = TARGETS[i];

    if (!results[reepId]) results[reepId] = { ss_id: ssId, seasons: [] };

    const url = '/api/v1/player/' + ssId + '/unique-tournament/' + utId + '/season/' + seasonId + '/statistics/overall';
    try {
      const resp = await fetch(url, {headers: HDRS});
      const data = await resp.json();
      if (data && data.error) {
        errors++;
        if (data.error.code === 403) { console.error('[CS2] 403 — aborting at', i); break; }
      } else {
        results[reepId].seasons.push({
          ut_id:      utId,
          season_id:  seasonId,
          ut_name:    utName,
          year:       year,
          statistics: data.statistics || {},
          team:       data.team       || {},
        });
        fetched++;
      }
    } catch(e) {
      errors++;
    }

    if ((i + 1) % 100 === 0) {
      console.log('[CS2] ' + (i+1) + '/' + TARGETS.length + '  fetched=' + fetched + '  errors=' + errors);
    }
    await sleep(DELAY_MS);
  }

  console.log('[CS2] Done — fetched=' + fetched + ' errors=' + errors + ' — downloading...');
  downloadJson(results, 'club_stats_p2_results.json');
}

run();
"""

out = Path("data/bronze/sofascore_browser_fetch_p2.js")
out.write_text(js, encoding="utf-8")
size_kb = out.stat().st_size / 1024
print(f"Written: {out}  ({size_kb:.1f} KB)")
print(f"Targets: {len(targets)}  |  Est. runtime: {len(targets)*0.7/60:.0f} min")
