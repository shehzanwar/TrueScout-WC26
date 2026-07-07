import type { Metadata } from "next"
import Link from "next/link"

export const metadata: Metadata = {
  title: "Methodology",
  description: "Technical writeup: Bayesian player ratings, Monte Carlo bracket simulation, calibration, and data pipeline.",
  openGraph: {
    title: "Methodology · TrueScout WC 2026",
    description: "How the Bayesian rating model, Monte Carlo simulation, and nightly ETL pipeline work under the hood.",
    type: "website",
  },
}

// ---------------------------------------------------------------------------
// Primitives
// ---------------------------------------------------------------------------

function Section({ id, title, children }: { id?: string; title: string; children: React.ReactNode }) {
  return (
    <section id={id} className="space-y-4 scroll-mt-8">
      <h2 className="text-lg font-semibold text-slate-100 border-b border-slate-800 pb-2">{title}</h2>
      {children}
    </section>
  )
}

function Prose({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-slate-400 leading-relaxed">{children}</p>
}

function CodeBlock({ children }: { children: React.ReactNode }) {
  return (
    <pre className="bg-slate-900 border border-slate-700 rounded-lg px-4 py-3 text-xs text-emerald-300 font-mono overflow-x-auto leading-relaxed">
      {children}
    </pre>
  )
}

function Callout({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3 rounded-lg bg-slate-800/60 border border-slate-700/50 px-4 py-3">
      <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider shrink-0 mt-0.5 w-16">{label}</span>
      <p className="text-sm text-slate-400 leading-relaxed">{children}</p>
    </div>
  )
}

function Limitation({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <li className="flex gap-3">
      <span className="w-1.5 h-1.5 rounded-full bg-amber-500/60 shrink-0 mt-[7px]" />
      <div>
        <p className="text-sm text-slate-300 font-medium">{title}</p>
        <p className="text-xs text-slate-500 leading-relaxed mt-0.5">{children}</p>
      </div>
    </li>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function MethodologyPage() {
  return (
    <div className="max-w-2xl mx-auto space-y-10">

      {/* Header */}
      <div>
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-600 mb-1">
          <Link href="/about" className="hover:text-slate-400 transition-colors">About</Link>
          {" / "}
          <span className="text-slate-500">Methodology</span>
        </p>
        <h1 className="text-2xl font-bold text-slate-100">How the model works</h1>
        <p className="mt-1 text-sm text-slate-500">
          Technical companion to the plain-English <Link href="/about" className="underline underline-offset-2 hover:text-slate-400">About page</Link>.
          Describes every step from raw data to the numbers on screen.
        </p>
      </div>

      {/* ── 1. Problem statement ─────────────────────────────────────────── */}
      <Section id="problem" title="1. The cross-league comparison problem">
        <Prose>
          Comparing Kylian Mbappé (Ligue 1) to Vinicius Júnior (La Liga) purely on raw statistics
          is misleading — league quality, team strength, and minutes played all distort the numbers.
          A simple mean of their Sofascore match ratings ignores how hard each game was, how much
          data we have on them, and how their club form should translate to a World Cup squad.
        </Prose>
        <Prose>
          TrueScout solves this with a two-stage approach: (1) pull club-level xG and xA from
          Understat and adjust for league strength using Club Elo coefficients, then (2) update
          those priors with in-tournament Sofascore match ratings as the World Cup progresses.
          The result is a single posterior estimate per player that naturally accounts for data
          volume and cross-competition quality.
        </Prose>
      </Section>

      {/* ── 2. Data pipeline ─────────────────────────────────────────────── */}
      <Section id="pipeline" title="2. Data pipeline (Bronze → Silver → Gold)">
        <Prose>
          The nightly ETL runs in three medallion layers, triggered automatically each night
          and after each round of matches:
        </Prose>

        {/* Pipeline flow diagram */}
        <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <svg viewBox="0 0 680 260" xmlns="http://www.w3.org/2000/svg" className="w-full max-w-2xl mx-auto" style={{ minWidth: 480 }}>
            {/* ── Source boxes ── */}
            {[
              { x: 10,  label: "ESPN",       sub: "results · odds" },
              { x: 120, label: "Sofascore",  sub: "ratings · lineups" },
              { x: 250, label: "Understat",  sub: "xG · xA" },
              { x: 380, label: "Reep",       sub: "player IDs" },
            ].map(({ x, label, sub }) => (
              <g key={label}>
                <rect x={x} y={8} width={96} height={46} rx={6} fill="#0f172a" stroke="#334155" strokeWidth={1.5} />
                <text x={x + 48} y={28} textAnchor="middle" fill="#94a3b8" fontSize={11} fontWeight={600}>{label}</text>
                <text x={x + 48} y={42} textAnchor="middle" fill="#475569" fontSize={9}>{sub}</text>
              </g>
            ))}

            {/* ── Down arrows to Bronze ── */}
            {[57, 167, 297, 427].map((cx) => (
              <g key={cx}>
                <line x1={cx} y1={54} x2={cx} y2={72} stroke="#1e3a5f" strokeWidth={1.5} />
                <polygon points={`${cx-4},69 ${cx+4},69 ${cx},76`} fill="#1e3a5f" />
              </g>
            ))}

            {/* ── Bronze bar ── */}
            <rect x={10} y={76} width={513} height={44} rx={7} fill="#0c1f38" stroke="#1d4ed8" strokeWidth={1.5} />
            <text x={266} y={96} textAnchor="middle" fill="#60a5fa" fontSize={11} fontWeight={700}>Bronze Layer</text>
            <text x={266} y={111} textAnchor="middle" fill="#3b82f6" fontSize={9}>Raw parquet files · append-only · one file per source per day</text>

            {/* ── Arrow to Silver ── */}
            <line x1={266} y1={120} x2={266} y2={138} stroke="#1e3a5f" strokeWidth={1.5} />
            <polygon points="262,135 270,135 266,142" fill="#1e3a5f" />

            {/* ── Silver bar ── */}
            <rect x={60} y={142} width={412} height={44} rx={7} fill="#0d1f1a" stroke="#059669" strokeWidth={1.5} />
            <text x={266} y={162} textAnchor="middle" fill="#34d399" fontSize={11} fontWeight={700}>Silver Layer</text>
            <text x={266} y={177} textAnchor="middle" fill="#10b981" fontSize={9}>features.parquet · one row per player · opponent-adjusted form + club priors</text>

            {/* ── Arrow to Gold ── */}
            <line x1={266} y1={186} x2={266} y2={204} stroke="#1e3a5f" strokeWidth={1.5} />
            <polygon points="262,201 270,201 266,208" fill="#1e3a5f" />

            {/* ── Gold bar ── */}
            <rect x={110} y={208} width={312} height={44} rx={7} fill="#1c1405" stroke="#d97706" strokeWidth={1.5} />
            <text x={266} y={228} textAnchor="middle" fill="#fbbf24" fontSize={11} fontWeight={700}>Gold Layer</text>
            <text x={266} y={243} textAnchor="middle" fill="#f59e0b" fontSize={9}>DuckDB · ratings · simulations · brier log · archetypes → static JSON → Vercel CDN</text>
          </svg>
        </div>

        <div className="space-y-3 pt-1">
          {[
            ["Bronze", "Raw parquet files from ESPN (match results, odds), Sofascore (player ratings, lineups, market values), and Understat (xG/xA by club season). Append-only — each nightly pull adds new rows, never overwrites."],
            ["Silver", "Cleaned and joined features.parquet — one row per player containing WC match aggregates, club priors, league Elo coefficients, and opponent-adjusted form ratings."],
            ["Gold", "DuckDB tables (player_ratings, simulations, brier_log, archetypes) that power the static JSON export. The frontend reads only from this layer."],
          ].map(([layer, desc]) => (
            <div key={layer as string} className="flex gap-3 items-start">
              <span className="text-xs font-mono font-bold text-emerald-400 shrink-0 w-14 mt-0.5">{layer as string}</span>
              <p className="text-sm text-slate-400 leading-snug">{desc as string}</p>
            </div>
          ))}
        </div>
        <Callout label="Deploy">
          Static JSON files in <code className="text-emerald-400">frontend/public/data/</code> are
          committed after each nightly run and served by Vercel&apos;s CDN — no backend needed in
          production.
        </Callout>
      </Section>

      {/* ── 3. Bayesian rating ───────────────────────────────────────────── */}
      <Section id="bayesian" title="3. Bayesian player rating (Normal–Normal conjugate)">
        <Prose>
          Each player&apos;s rating is modelled as a Normal–Normal conjugate update. The prior comes
          from club xG and xA (last 2 seasons, older season weighted by exp(−1) ≈ 37%); the
          likelihood comes from Sofascore WC match ratings, themselves adjusted for opponent
          strength and time-decayed with a 60-day half-life.
        </Prose>
        <CodeBlock>{`# Prior: league-Elo-adjusted club composite
prior_mean = (xg_per_90 + xa_per_90) × elo_coefficient
prior_var  = σ²_prior   # position-cluster variance

# Likelihood: WC form (time-decay-weighted)
n_eff     = Σ(minutes × decay_weight) / 90
lhood_mean = wc_rating_decay_avg
lhood_var  = σ²_wc / n_eff

# Posterior (closed-form Normal–Normal)
posterior_mean = (prior_mean/prior_var + lhood_mean/lhood_var)
              / (1/prior_var + 1/lhood_var)
posterior_var  = 1 / (1/prior_var + 1/lhood_var)`}
        </CodeBlock>
        <Prose>
          The <strong className="text-slate-200">shrinkage weight</strong> (fraction of the final
          rating from the prior) falls as a player accumulates WC minutes — a player with 270
          minutes typically sits around 60–70% club / 30–40% WC. A player with 45 minutes barely
          updates from their prior.
        </Prose>
        <Prose>
          <strong className="text-slate-200">League Elo coefficients</strong> are derived from
          Club Elo ratings: EPL = 1.000 (reference), La Liga ≈ 0.985, Serie A ≈ 0.955,
          Ligue 1 ≈ 0.930, MLS ≈ 0.685, Saudi Pro ≈ 0.645. Non-big-5 players whose clubs have
          no Understat data receive a prior of 0 (pure WC form only).
        </Prose>
        <Prose>
          <strong className="text-slate-200">Opponent-strength adjustment</strong> re-weights each
          WC match rating by the opponent&apos;s mean top-15 squad strength. A 7.5 against France
          counts more than a 7.5 against a weaker side.
        </Prose>
      </Section>

      {/* ── 4. Radar ─────────────────────────────────────────────────────── */}
      <Section id="radar" title="4. Position-aware radar axes">
        <Prose>
          The five-axis radar computes a 0–1 percentile score per axis within each position group
          (GK / DEF / MID / FWD). The axes and their weights vary by position:
        </Prose>
        <div className="overflow-x-auto">
          <table className="w-full text-xs text-left">
            <thead>
              <tr className="border-b border-slate-800">
                {["Axis", "FWD", "MID", "DEF", "GK"].map(h => (
                  <th key={h} className="pb-2 pr-4 text-slate-500 font-semibold">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="text-slate-400 space-y-1">
              {[
                ["Shooting (xG, shots)", "60%", "25%", "10%", "—"],
                ["Creativity (xA, KP)", "25%", "45%", "20%", "—"],
                ["Defending (tkl, int)", "5%", "20%", "60%", "—"],
                ["WC Form (rating)", "10%", "10%", "10%", "20%"],
                ["Saves / Distribution", "—", "—", "—", "80%"],
              ].map(([axis, ...vals]) => (
                <tr key={axis as string} className="border-b border-slate-800/50">
                  <td className="py-1.5 pr-4 text-slate-300">{axis as string}</td>
                  {vals.map((v, i) => <td key={i} className="py-1.5 pr-4">{v as string}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Prose>
          All axis scores are converted to FIFA-style 0–99 integers for display. Each axis
          tooltip on the player profile shows the underlying raw statistic.{" "}
          <Link href="/players/mbappe-reep_p4b7614c5" className="text-emerald-500 hover:text-emerald-400 transition-colors underline underline-offset-2">
            See Mbappé&apos;s radar as an example →
          </Link>
        </Prose>
      </Section>

      {/* ── 5. Monte Carlo ───────────────────────────────────────────────── */}
      <Section id="simulation" title="5. Monte Carlo bracket simulation">
        <Prose>
          100,000 tournament iterations run nightly using a vectorised NumPy implementation.
          Each iteration samples a winner for every match using a logistic win probability:
        </Prose>
        <CodeBlock>{`P(team A wins) = 1 / (1 + 10^(−(strength_A − strength_B) / SCALE))

# where:
#   strength = mean posterior_mean of top-15 rated players
#   SCALE    = fitted nightly by grid-search to minimise log-loss
#              on all graded WC knockout matches`}
        </CodeBlock>
        <Prose>
          Three adjustments are applied to strength before each simulation:
        </Prose>
        <div className="space-y-2">
          {[
            ["Rest penalty", "−0.10 × max(0, 3 − rest_days) per team. Teams with fewer than 3 days since their last match are penalised. Derived from match date chronology in Bronze."],
            ["Venue / home advantage", "Host nations playing at home venues receive a boost: Mexico +0.30 (home crowd + Azteca altitude ~2,240 m), USA +0.15, Canada +0.15. Opponents playing Mexico at Mexican venues receive −0.10 altitude penalty."],
            ["Market-value prior", "Squad market values (Transfermarkt via Sofascore) shift a player's prior toward their market-implied worth. Absent when market data is unavailable."],
          ].map(([label, desc]) => (
            <div key={label as string} className="flex gap-3 items-start">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500/60 shrink-0 mt-[7px]" />
              <div>
                <p className="text-sm text-slate-300 font-medium">{label as string}</p>
                <p className="text-xs text-slate-500 leading-snug mt-0.5">{desc as string}</p>
              </div>
            </div>
          ))}
        </div>
        <Prose>
          The simulation preserves the joint distribution of per-bracket-slot winners —
          not just marginal advance probabilities. This fixes the coherence issue where
          a team with lower marginal probability could appear to beat a stronger neighbour
          in the bracket visualisation.
        </Prose>
      </Section>

      {/* ── 6. Calibration ───────────────────────────────────────────────── */}
      <Section id="calibration" title="6. Validation and calibration">
        <Prose>
          After each completed knockout match, the nightly Brier tracker grades the model:
          it records the pre-match model probability, the bookmaker implied probability,
          and the actual outcome. These ground-truth pairs drive the{" "}
          <strong className="text-slate-200">logistic scale calibration</strong> — a nightly
          grid search that finds the SCALE constant minimising log-loss on all graded matches.
        </Prose>
        <Prose>
          The <Link href="/brier" className="underline underline-offset-2 hover:text-slate-300">
          Track Record page</Link> shows every graded match with model vs. bookmaker predictions
          and the actual result. We publish this unconditionally — if the model is wrong,
          the page says so.
        </Prose>
        <Callout label="Note">
          With N &lt; 20 graded matches the Brier score has wide confidence intervals. We defer
          isotonic post-hoc calibration until after the Semi-Finals when the sample is large
          enough to be statistically meaningful.
        </Callout>
      </Section>

      {/* ── 7. Limitations ───────────────────────────────────────────────── */}
      <Section id="limitations" title="7. Known limitations">
        <ul className="space-y-4">
          <Limitation title="Small knockout sample">
            Brier score and calibration are estimated on a single tournament&apos;s worth of
            knockout matches (~25–30 graded games at most). Confidence intervals are wide until
            the Semi-Final week.
          </Limitation>
          <Limitation title="Sofascore ratings are a black box">
            The match ratings that feed the WC-form likelihood are themselves an ML model
            (Sofascore&apos;s own). We don&apos;t have access to their inputs or uncertainty estimates.
          </Limitation>
          <Limitation title="Club stats limited to big-5 leagues">
            Understat covers the EPL, La Liga, Bundesliga, Serie A, and Ligue 1 only.
            Players from MLS, Saudi Pro League, and other leagues receive a prior of 0 —
            their rating is purely driven by WC minutes and a market-value adjustment.
          </Limitation>
          <Limitation title="Static role assumption">
            The model treats each player&apos;s role as fixed. A midfielder who plays as a shadow
            striker at the World Cup but was a box-to-box mid at his club will be evaluated
            on club data that may not reflect his tournament role.
          </Limitation>
          <Limitation title="No event-level data">
            xT (expected threat), VAEP (valuing actions by estimated probabilities), and
            pass-network analysis all require event-level data (StatsBomb, Opta). These
            sources are behind licensing walls we don&apos;t have access to.
          </Limitation>
          <Limitation title="Penalty shootouts">
            Shootouts are treated as a coin flip. No shootout-specialist data or historical
            penalty conversion rates are modelled.
          </Limitation>
          <Limitation title="No injury or selection feed">
            The model uses the last known squad data and does not update for late injuries,
            tactical omissions, or yellow-card suspensions unless Sofascore lineup data
            for the specific match is scraped before kickoff.
          </Limitation>
          <Limitation title="Rest / travel constants are judgment calls">
            The −0.10 per rest-day-deficit and venue-boost coefficients are manually set
            based on published research ranges, not fitted to this specific tournament.
            We will derive them empirically once we have ≥20 graded matches.
          </Limitation>
        </ul>
      </Section>

      {/* Footer nav */}
      <div className="flex items-center justify-between pt-4 border-t border-slate-800">
        <div className="flex gap-4 text-xs text-slate-600">
          <Link href="/about" className="hover:text-slate-400 transition-colors">← Plain-English About</Link>
          <Link href="/brier" className="hover:text-slate-400 transition-colors">Track Record →</Link>
        </div>
        <p className="text-xs text-slate-800 font-mono">v0.2</p>
      </div>

    </div>
  )
}
