// ============================================================
// TrueScout — Sofascore player profile fetch for identity matching
// Paste in DevTools console on www.sofascore.com
// Downloads player_profiles.json (~60s for 116 players)
//
// Usage:
//   1. Open www.sofascore.com in Chrome
//   2. Open DevTools → Console
//   3. Paste this entire script and press Enter
//   4. Wait for the download prompt (player_profiles.json)
//   5. Run: python -m etl.sources.sofascore_wc_identity_import
// ============================================================

const TARGETS = [
  ["1503088", "Achref Abada", "Algeria"],
  ["1018018", "Mohamed Tougai", "Algeria"],
  ["788284", "Ajdin Hrustic", "Australia"],
  ["181581", "Jackson Irvine", "Australia"],
  ["1411105", "Paul Okon-Engstler", "Australia"],
  ["994556", "Carney Chukwuemeka", "Austria"],
  ["870038", "Sasa Kaladjzic", "Austria"],
  ["1587186", "Mladen Jurkas", "Bosnia & Herzegovina"],
  ["831005", "Raphinha", "Brazil"],
  ["815080", "Jamiro Monteiro", "Cabo Verde"],
  ["911853", "Logan Costa", "Cabo Verde"],
  ["147138", "Pico", "Cabo Verde"],
  ["52797", "Ryan Mendes", "Cabo Verde"],
  ["273031", "Jonathan Osorio", "Canada"],
  ["902083", "Liam Millar", "Canada"],
  ["155736", "Maxime Crepeau", "Canada"],
  ["980580", "Juan Portilla", "Colombia"],
  ["931705", "Willer Ditta", "Colombia"],
  ["884944", "Jurien Gaari", "Curacao"],
  ["1049270", "Tyrick Bodak", "Curacao"],
  ["1931626", "Hugo Sochurek", "Czechia"],
  ["843754", "Ibrahim Sangare", "Cote d'Ivoire"],
  ["353602", "Aaron Tshibola", "DR Congo"],
  ["1160969", "Brian Cipenga", "DR Congo"],
  ["238612", "Chancel Mbemba", "DR Congo"],
  ["758664", "Charles Pickel", "DR Congo"],
  ["352912", "Dylan Batubinsika", "DR Congo"],
  ["918913", "Hamdy Fathy", "Egypt"],
  ["918547", "Mahdi Soliman", "Egypt"],
  ["1980828", "Mohamed Alaa", "Egypt"],
  ["1418782", "Mostafa Ziko", "Egypt"],
  ["1480544", "Tarek Alaa", "Egypt"],
  ["966547", "Noni Madueke", "England"],
  ["798583", "Dayot Upamecano", "France"],
  ["259117", "Joshua Kimmich", "Germany"],
  ["934354", "Antoine Semenyo", "Ghana"],
  ["1457083", "Benjamin Asare", "Ghana"],
  ["846061", "Brandon Thomas-Asante", "Ghana"],
  ["783374", "Inaki Williams", "Ghana"],
  ["970370", "Joseph Anang", "Ghana"],
  ["791092", "Lawrence Ati Zigi", "Ghana"],
  ["828012", "Derrick Etienne", "Haiti"],
  ["936558", "Josue Duverger", "Haiti"],
  ["1384367", "Woodensky Pierre", "Haiti"],
  ["223340", "Shoja Khalilzadeh", "Iran"],
  ["888896", "Ahmed Basil", "Iraq"],
  ["915325", "Amir Al-Ammari", "Iraq"],
  ["1163991", "Munaf Younus", "Iraq"],
  ["1843356", "Zaid Ismail", "Iraq"],
  ["1457997", "Ali Al Azaizeh", "Jordan"],
  ["2239188", "Anas Badawi", "Jordan"],
  ["1122369", "Husam Ali Mohammad Abudahab", "Jordan"],
  ["997817", "Ibrahim Sadeh", "Jordan"],
  ["1158813", "Mo Abualnadi", "Jordan"],
  ["2048339", "Mohammad Abu Ghoush", "Jordan"],
  ["986341", "Mohammad Abu Zrayq", "Jordan"],
  ["786034", "Mohammad Al Daoud", "Jordan"],
  ["954107", "Noureddin Zaid", "Jordan"],
  ["920476", "Saad Al Rousan", "Jordan"],
  ["980664", "Saleem Obaid", "Jordan"],
  ["828294", "Yazeed Abu Laila", "Jordan"],
  ["1172773", "Luis Romo", "Mexico"],
  ["192442", "Raul Jimenez", "Mexico"],
  ["1392829", "Amine Sbai", "Morocco"],
  ["919793", "Ayoub El Kaabi", "Morocco"],
  ["953995", "Soufiane Rahimi", "Morocco"],
  ["360938", "Yassine Bounou", "Morocco"],
  ["959750", "Callan Elliot", "New Zealand"],
  ["333571", "Ryan Thomas", "New Zealand"],
  ["159931", "Cecilio Waterman", "Panama"],
  ["1217937", "Edgardo Farina", "Panama"],
  ["159939", "Roderick Miller", "Panama"],
  ["788936", "Alejandro Romero", "Paraguay"],
  ["1105836", "Matias Galarza", "Paraguay"],
  ["840027", "Roberto Fernandez", "Paraguay"],
  ["229278", "Ahmed Alaaeldin", "Qatar"],
  ["911427", "Ahmed Fathi", "Qatar"],
  ["1396639", "Ayoub Al Oui", "Qatar"],
  ["93953", "Hassan Al Haydos", "Qatar"],
  ["933433", "Homam Al-Amin", "Qatar"],
  ["1892282", "Issa Laye", "Qatar"],
  ["1012458", "Mahmud Abunada", "Qatar"],
  ["891157", "Meshaal Barsham", "Qatar"],
  ["1083016", "Mohamed Naceur Almanai", "Qatar"],
  ["796497", "Sultan Al-Brake", "Qatar"],
  ["1501518", "Tahsin Mohammed Jamshid", "Qatar"],
  ["818749", "Ahmed Al-Kassar", "Saudi Arabia"],
  ["826242", "Alaa Al-Hejji", "Saudi Arabia"],
  ["847235", "Hassan Kadesh", "Saudi Arabia"],
  ["818779", "Saleh Al-Shehri", "Saudi Arabia"],
  ["818568", "Sultan Mandash", "Saudi Arabia"],
  ["1048372", "Ziyad Aljohani", "Saudi Arabia"],
  ["886117", "Ross Stewart", "Scotland"],
  ["1402850", "Tyler Fletcher", "Scotland"],
  ["1085536", "Bradley Cross", "South Africa"],
  ["1210653", "Kamogelo Sebelebele", "South Africa"],
  ["1910804", "Khulumani Ndamane", "South Africa"],
  ["2058228", "Mbekezeli Mbokazi", "South Africa"],
  ["966059", "Ricardo Goss", "South Africa"],
  ["1179164", "Thapelo Maseko", "South Africa"],
  ["1470073", "Tholo Thabang Matuludi", "South Africa"],
  ["1010634", "Hyeon-gyu Oh", "South Korea"],
  ["1009476", "Jin-gyu Kim", "South Korea"],
  ["1154613", "Wi-je Cho", "South Korea"],
  ["149734", "Aymeric Laporte", "Spain"],
  ["1005744", "Marvin Keller", "Switzerland"],
  ["2018130", "Abdelmouhib Chamakh", "Tunisia"],
  ["1000809", "Amine Ben Hmida", "Tunisia"],
  ["2018330", "Raed Chikhaoui", "Tunisia"],
  ["359312", "Sabri Ben Hessen", "Tunisia"],
  ["822459", "Auston Trusty", "USA"],
  ["954524", "Abdulla Abdullaev", "Uzbekistan"],
  ["926479", "Akmal Mozgovoy", "Uzbekistan"],
  ["978392", "Avazbek Ulmasaliyev", "Uzbekistan"],
  ["1597255", "Bekhruz Karimov", "Uzbekistan"],
  ["792386", "Farrukh Sayfiev", "Uzbekistan"]
];

const DELAY_MS = 500;
// x-captcha expires ~7h from capture — refresh from DevTools Network tab if it starts 403ing.
// How to get a fresh token: open any player page on sofascore.com, look in Network tab for
// a request to /api/v1/player/... and copy the x-captcha request header value.
const XCAPTCHA = 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJleHAiOjE3ODMxMzUyMzQsImlwIjoiMTA3LjE5My4xNDAuMTk3IiwiZiI6IjlhMTJkNSJ9.iMCDgIxbCHV7MHOfuh4JzoaasUIrTpVnK0y0qVDANpk';
const HDRS = { 'accept': '*/*', 'x-requested-with': '740d88', 'x-captcha': XCAPTCHA };

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function downloadJson(obj, fn) {
  const b = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' });
  const u = URL.createObjectURL(b);
  const a = document.createElement('a');
  a.href = u; a.download = fn; a.click();
  setTimeout(() => URL.revokeObjectURL(u), 5000);
}

async function probe() {
  // Probe with Yassine Bounou (Moroccan GK — one of the known unmatched players)
  console.log('[PROBE] Testing with Yassine Bounou (ss=360938)...');
  const resp = await fetch('/api/v1/player/360938', { headers: HDRS });
  if (!resp.ok) {
    console.error('[PROBE] HTTP', resp.status,
      '— make sure you are on www.sofascore.com and logged in (or try after browsing a player page).');
    return false;
  }
  const data = await resp.json();
  if (!data || !data.player) {
    console.error('[PROBE] Unexpected shape:', JSON.stringify(data).slice(0, 300));
    return false;
  }
  console.log('[PROBE] OK — got profile for:', data.player.name);
  return true;
}

async function fetchProfiles() {
  const ok = await probe();
  if (!ok) return;
  await sleep(700);

  console.log('[PP] Fetching profiles for', TARGETS.length, 'players...');
  const results = {};
  let errors = 0;

  for (let i = 0; i < TARGETS.length; i++) {
    const [ssId, lineupName, team] = TARGETS[i];
    try {
      const resp = await fetch('/api/v1/player/' + ssId, { headers: HDRS });
      if (!resp.ok) {
        results[ssId] = { error: resp.status, lineup_name: lineupName, national_team: team };
        errors++;
        if (resp.status === 403) {
          console.error('[PP] 403 at', lineupName, '— aborting. Browse a few player pages first then retry.');
          break;
        }
      } else {
        const data = await resp.json();
        const profile = data.player || {};
        results[ssId] = {
          id:                   profile.id,
          name:                 profile.name,
          shortName:            profile.shortName,
          position:             profile.position,
          height:               profile.height,
          dateOfBirthTimestamp: profile.dateOfBirthTimestamp,
          country:              profile.country ? profile.country.name : null,
          lineup_name:          lineupName,
          national_team:        team,
        };
      }
    } catch (e) {
      results[ssId] = { error: String(e), lineup_name: lineupName, national_team: team };
      errors++;
    }

    if ((i + 1) % 25 === 0) {
      console.log('[PP]', (i + 1) + '/' + TARGETS.length, '  errors so far:', errors);
    }
    await sleep(DELAY_MS + Math.random() * 300);
  }

  const n = Object.keys(results).length;
  console.log('[PP] Done —', n, 'entries,', errors, 'errors. Downloading player_profiles.json...');
  downloadJson(results, 'player_profiles.json');
}

fetchProfiles();
