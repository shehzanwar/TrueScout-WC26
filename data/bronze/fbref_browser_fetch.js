// ============================================================
// TrueScout — FBref international form browser fetch
// Paste in DevTools console on https://fbref.com (any page)
// Fetches 11 competition pages, parses stats_standard table,
// downloads fbref_intl_form_results.json when done (~2 min).
// ============================================================

const COMPETITIONS = [
  { label: "WC 2026",                     url: "/en/comps/1/2026/stats/2026-FIFA-World-Cup-Stats" },
  { label: "UEFA Euro 2024",              url: "/en/comps/676/2024/stats/2024-UEFA-European-Championship-Stats" },
  { label: "Copa America 2024",           url: "/en/comps/685/2024/stats/2024-Copa-America-Stats" },
  { label: "Africa Cup of Nations 2023",  url: "/en/comps/656/2023/stats/2023-Africa-Cup-of-Nations-Stats" },
];

const DELAY_MS   = 5000;   // 5s between requests — FBref rate limit
const FBREF_ID_RE = /\/players\/([0-9a-f]{8})\//;

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function downloadJson(obj, fn) {
  const b = new Blob([JSON.stringify(obj)], { type: 'application/json' });
  const u = URL.createObjectURL(b);
  const a = document.createElement('a');
  a.href = u; a.download = fn; a.click();
  setTimeout(() => URL.revokeObjectURL(u), 5000);
}

function getStat(tr, statName) {
  const td = tr.querySelector('td[data-stat="' + statName + '"]');
  if (!td) return null;
  const v = td.textContent.trim();
  return (v === '' || v === '-') ? null : parseFloat(v) || null;
}

function parseTable(html, label) {
  // FBref sometimes puts non-featured tables inside HTML comments.
  // Strategy: try live DOM first; if not found, uncomment and re-parse.
  let doc = new DOMParser().parseFromString(html, 'text/html');
  let table = doc.getElementById('stats_standard');

  if (!table) {
    // Uncomment all HTML comments and re-parse
    const uncommented = html.replace(/<!--([\s\S]*?)-->/g, '$1');
    doc = new DOMParser().parseFromString(uncommented, 'text/html');
    table = doc.getElementById('stats_standard');
  }

  if (!table) {
    console.warn('[' + label + '] stats_standard table not found');
    return [];
  }

  const tbody = table.querySelector('tbody');
  if (!tbody) return [];

  const rows = [];
  for (const tr of tbody.querySelectorAll('tr')) {
    const cls = tr.className || '';
    if (cls.includes('thead') || cls.includes('spacer') || cls.includes('partial_table')) continue;

    const playerTd = tr.querySelector('td[data-stat="player"]');
    if (!playerTd) continue;
    const a = playerTd.querySelector('a');
    if (!a) continue;

    const href  = a.getAttribute('href') || '';
    const match = href.match(FBREF_ID_RE);
    if (!match) continue;

    const mins = getStat(tr, 'minutes');
    if (!mins || mins <= 0) continue;

    rows.push({
      fbref_id:    match[1],
      player_name: a.textContent.trim(),
      nation:      tr.querySelector('td[data-stat="nationality"]')?.textContent?.trim() || null,
      minutes:     mins,
      goals:       getStat(tr, 'goals'),
      assists:     getStat(tr, 'assists'),
      xg:          getStat(tr, 'xg'),
      xa:          getStat(tr, 'xg_assist'),
      npxg:        getStat(tr, 'npxg'),
    });
  }
  return rows;
}

async function run() {
  console.log('[FBref] Starting — ' + COMPETITIONS.length + ' competitions, ~' + Math.round(COMPETITIONS.length * DELAY_MS / 60000) + ' min');
  const results = {};

  for (let i = 0; i < COMPETITIONS.length; i++) {
    const { label, url } = COMPETITIONS[i];
    console.log('[FBref] (' + (i+1) + '/' + COMPETITIONS.length + ') Fetching ' + label + ' ...');

    try {
      const resp = await fetch(url, { credentials: 'include' });
      if (resp.status === 404) {
        console.warn('[FBref] 404 — ' + label + ' not on FBref yet, skipping');
      } else if (!resp.ok) {
        console.warn('[FBref] HTTP ' + resp.status + ' for ' + label);
      } else {
        const html  = await resp.text();
        const rows  = parseTable(html, label);
        results[label] = rows;
        console.log('[FBref] ' + label + ' — ' + rows.length + ' players parsed');
      }
    } catch(e) {
      console.error('[FBref] Error on ' + label + ':', e);
    }

    if (i < COMPETITIONS.length - 1) await sleep(DELAY_MS);
  }

  const total = Object.values(results).reduce((s, r) => s + r.length, 0);
  console.log('[FBref] Done — ' + total + ' total player rows across ' + Object.keys(results).length + ' competitions');
  downloadJson(results, 'fbref_intl_form_results.json');
}

run();
