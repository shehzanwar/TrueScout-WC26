// TrueScout — Club Stats structure probe
// Paste into DevTools console on www.sofascore.com
// Downloads cs_debug.json (3 players, full raw response + parsed attempt)

(async () => {
  const TEST = [
    ['reep_pfe462b4c', '1118429'],
    ['reep_pfc1f5c60', '974747'],
    ['reep_p2d857678', '1114497']
  ];
  const out = {};

  for (const [reepId, ssId] of TEST) {
    const resp = await fetch('/api/v1/player/' + ssId + '/statistics/seasons', {
      headers: { 'accept': 'application/json' }
    });
    const text = await resp.text();
    let data;
    try { data = JSON.parse(text); } catch(e) { data = { _parseError: text.slice(0, 200) }; }

    const topLevelKeys = data ? Object.keys(data) : [];
    const statsVal     = data && data.statistics;
    const statsType    = Array.isArray(statsVal) ? 'array[' + statsVal.length + ']'
                       : statsVal === null       ? 'null'
                       : typeof statsVal;

    const seasonsVal   = statsVal && !Array.isArray(statsVal) && statsVal.seasons;
    const seasonsType  = Array.isArray(seasonsVal) ? 'array[' + seasonsVal.length + ']'
                       : seasonsVal === null        ? 'null'
                       : typeof seasonsVal;

    out[reepId] = {
      ss_id:          ssId,
      http_status:    resp.status,
      top_level_keys: topLevelKeys,
      statistics_type: statsType,
      seasons_type:   seasonsType,
      // First season object keys (whichever path has data)
      first_season_keys: (
        Array.isArray(statsVal) && statsVal.length
          ? Object.keys(statsVal[0])
          : Array.isArray(seasonsVal) && seasonsVal.length
            ? Object.keys(seasonsVal[0])
            : null
      ),
      // Raw snippet for manual inspection
      raw_snippet: text.slice(0, 600),
    };

    console.log('[DEBUG]', ssId, 'HTTP', resp.status,
                '| stats:', statsType, '| seasons:', seasonsType);
    await new Promise(r => setTimeout(r, 1000));
  }

  const blob = new Blob([JSON.stringify(out, null, 2)], {type: 'application/json'});
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url; a.download = 'cs_debug.json'; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
  console.log('[DEBUG] Done — downloaded cs_debug.json');
})();
