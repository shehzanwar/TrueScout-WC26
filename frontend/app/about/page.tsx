import type { Metadata } from "next"
import Link from "next/link"
import { getBrier } from "@/lib/server-data"

export const metadata: Metadata = {
  title: "About",
  description: "How TrueScout's Bayesian model works — data sources, methodology, and limitations.",
  openGraph: {
    title: "About · TrueScout WC 2026",
    description: "How TrueScout's Bayesian model works — data sources, methodology, and limitations.",
    type: "website",
  },
  twitter: { card: "summary_large_image" },
}

// ---------------------------------------------------------------------------
// Shared primitives
// ---------------------------------------------------------------------------

function SectionNumber({ n, muted = false }: { n: number; muted?: boolean }) {
  return (
    <span
      className={[
        "w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold shrink-0",
        muted
          ? "bg-slate-700/60 border border-slate-600/40 text-slate-400"
          : "bg-emerald-500/15 border border-emerald-500/30 text-emerald-400",
      ].join(" ")}
    >
      {n}
    </span>
  )
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <section className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
      {children}
    </section>
  )
}

function SectionHeader({ n, title, muted = false }: { n: number; title: string; muted?: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <SectionNumber n={n} muted={muted} />
      <h2 className="text-base font-semibold text-slate-100">{title}</h2>
    </div>
  )
}

function Prose({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-slate-400 leading-relaxed">{children}</p>
}

function Em({ children }: { children: React.ReactNode }) {
  return <span className="text-slate-200 font-medium">{children}</span>
}

function Pill({ label, color = "slate" }: { label: string; color?: "emerald" | "sky" | "amber" | "slate" }) {
  const styles = {
    emerald: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
    sky:     "bg-sky-500/10    text-sky-400    border-sky-500/20",
    amber:   "bg-amber-500/10  text-amber-400  border-amber-500/20",
    slate:   "bg-slate-800     text-slate-400  border-slate-700",
  }[color]
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium border ${styles}`}>
      {label}
    </span>
  )
}

function Callout({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg bg-slate-800/60 border border-slate-700/50 px-4 py-3 text-sm text-slate-400 leading-relaxed">
      {children}
    </div>
  )
}

function LimitationItem({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <li className="flex gap-3">
      <span className="w-1.5 h-1.5 rounded-full bg-slate-600 shrink-0 mt-[7px]" />
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

export default async function AboutPage() {
  const brier = await getBrier().catch(() => null)
  const nMatches = brier?.summary.n_matches ?? 0
  const nCorrect = brier?.summary.n_correct ?? 0

  return (
    <div className="max-w-2xl mx-auto space-y-8">

      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-100">How TrueScout Works</h1>
        <p className="mt-1 text-sm text-slate-500">
          A plain-English guide to the model, the data, and what to trust
        </p>
      </div>

      <div className="space-y-4">

        {/* ── 1. What TrueScout is ─────────────────────────────────── */}
        <Card>
          <SectionHeader n={1} title="What TrueScout is" />
          <Prose>
            TrueScout is a statistical intelligence layer on top of the 2026 FIFA World Cup.
            It combines two years of club-season data with live tournament performance to
            produce a single, honest number for every player — and a bracket forecast that
            updates every night as results come in.
          </Prose>
          <Prose>
            The goal is not to predict the future with certainty. It is to tell you <Em>where
            the evidence points</Em> and to be honest when the evidence is thin.
          </Prose>
        </Card>

        {/* ── 2. Data sources ──────────────────────────────────────── */}
        <Card>
          <SectionHeader n={2} title="Data sources" />
          <Prose>
            Four external sources feed the nightly pipeline, each covering a different layer
            of the picture:
          </Prose>
          <div className="space-y-3 pt-1">
            <div className="flex gap-3 items-start">
              <Pill label="ESPN" color="sky" />
              <p className="text-sm text-slate-400 leading-snug">
                Match results, schedules, and pre-match bookmaker odds for every knockout
                fixture. Our primary source for win/loss outcomes and probability benchmarks.
              </p>
            </div>
            <div className="flex gap-3 items-start">
              <Pill label="Sofascore" color="sky" />
              <p className="text-sm text-slate-400 leading-snug">
                Player-level match ratings, minutes played, goals, assists, shots, tackles,
                and interceptions for every World Cup appearance. Also the source of squad
                market values via Transfermarkt data.
              </p>
            </div>
            <div className="flex gap-3 items-start">
              <Pill label="Understat" color="sky" />
              <p className="text-sm text-slate-400 leading-snug">
                Two seasons of club-level expected goals (xG), expected assists (xA), shots,
                and key passes from Europe&apos;s top five leagues. This is the foundation of
                each player&apos;s baseline rating before the tournament began.
              </p>
            </div>
            <div className="flex gap-3 items-start">
              <Pill label="Reep" color="slate" />
              <p className="text-sm text-slate-400 leading-snug">
                A comprehensive player identity database that links players across sources —
                resolving name variants, nationalities, and positional classifications across
                40 000+ professionals.
              </p>
            </div>
          </div>
          <Prose>
            The pipeline runs automatically every night at 02:00 UTC and re-exports all
            data to this site. What you see is never more than 24 hours old.
          </Prose>
        </Card>

        {/* ── 3. Player ratings ────────────────────────────────────── */}
        <Card>
          <SectionHeader n={3} title="How player ratings work" />
          <Prose>
            Every player gets a rating on a <Em>0–10 scale</Em>, derived from a
            statistical method called Bayesian inference. The idea is simple: start with
            what we know from club form, then update that belief as World Cup evidence
            accumulates.
          </Prose>
          <div className="space-y-2.5 py-1">
            <div className="flex gap-3 items-start">
              <span className="text-xs font-bold text-slate-500 uppercase tracking-wider w-16 shrink-0 mt-0.5">
                Step 1
              </span>
              <p className="text-sm text-slate-400 leading-snug">
                <Em>Club baseline.</Em> Understat xG, xA, key passes, and Sofascore ratings
                from the last two club seasons are combined into a single starting estimate
                of how good this player is.
              </p>
            </div>
            <div className="flex gap-3 items-start">
              <span className="text-xs font-bold text-slate-500 uppercase tracking-wider w-16 shrink-0 mt-0.5">
                Step 2
              </span>
              <p className="text-sm text-slate-400 leading-snug">
                <Em>World Cup evidence.</Em> Each appearance at the tournament updates the
                estimate. A strong performance lifts the rating; a poor one pulls it down.
                Performances against stronger opponents carry more weight.
              </p>
            </div>
            <div className="flex gap-3 items-start">
              <span className="text-xs font-bold text-slate-500 uppercase tracking-wider w-16 shrink-0 mt-0.5">
                Step 3
              </span>
              <p className="text-sm text-slate-400 leading-snug">
                <Em>The blend.</Em> The final rating is a weighted average of the two. The
                more minutes a player has logged at the World Cup, the more those performances
                dominate. A player with 10 minutes mostly reflects their club form; one with
                450 minutes is judged almost entirely on what they have done in this tournament.
              </p>
            </div>
          </div>
          <Callout>
            Example: Erling Haaland entered the tournament rated highly on club form. After
            three World Cup appearances (270 minutes), tournament data now carries <Em>~27%</Em> of
            his rating — enough to reflect genuine in-tournament evidence without discarding
            two seasons of club-level data.
          </Callout>
        </Card>

        {/* ── 4. Rating range & confidence ─────────────────────────── */}
        <Card>
          <SectionHeader n={4} title="Rating range and confidence" />
          <Prose>
            Every rating comes with a <Em>range</Em> — for example, 7.87–8.60 for Mbappé.
            This reflects genuine statistical uncertainty: with only three World Cup
            appearances, the model cannot pin down his true level to two decimal places. The
            range says &ldquo;we are confident he is somewhere in here.&rdquo; A player with ten
            appearances has a much tighter range; one with 45 minutes has a wide one.
          </Prose>
          <Prose>
            The confidence badge summarises this in three tiers:
          </Prose>
          <div className="flex flex-wrap gap-2.5 pt-1">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
              Reliable data — solid estimate
            </span>
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-500/15 text-amber-400 border border-amber-500/20">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
              Some data — reasonable estimate
            </span>
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-rose-500/15 text-rose-400 border border-rose-500/20">
              <span className="w-1.5 h-1.5 rounded-full bg-rose-400 shrink-0" />
              Limited data — treat as a guide
            </span>
          </div>
        </Card>

        {/* ── 5. FIFA-style 0–99 score ─────────────────────────────── */}
        <Card>
          <SectionHeader n={5} title="The 0–99 FIFA-style score" />
          <Prose>
            Each player also gets a score from <Em>0 to 99</Em>, displayed as a coloured
            badge. This is a direct rescaling of the 0–10 rating into a format that feels
            familiar — it carries no extra information, but makes it easier to compare
            players at a glance.
          </Prose>
          <div className="flex flex-wrap gap-2 pt-1 text-xs">
            {[
              { band: "World Class", range: "90–99", style: "bg-purple-500/15 text-purple-300 border border-purple-500/30" },
              { band: "Elite",       range: "85–89", style: "bg-amber-400/15  text-amber-300  border border-amber-400/30"  },
              { band: "Top Tier",    range: "80–84", style: "bg-amber-500/15  text-amber-400  border border-amber-500/30"  },
              { band: "Quality",     range: "70–79", style: "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30" },
              { band: "Good",        range: "60–69", style: "bg-sky-500/15    text-sky-400    border border-sky-500/30"    },
              { band: "Decent",      range: "50–59", style: "bg-slate-500/15  text-slate-400  border border-slate-500/30"  },
            ].map(({ band, range, style }) => (
              <span key={band} className={`px-2.5 py-1 rounded-full font-medium tabular-nums ${style}`}>
                {range} · {band}
              </span>
            ))}
          </div>
        </Card>

        {/* ── 6. Playing style archetypes ──────────────────────────── */}
        <Card>
          <SectionHeader n={6} title="Playing style archetypes" />
          <Prose>
            Players in the same position don&apos;t all play the same way. A defensive midfielder
            who sits and destroys is very different from one who carries the ball and picks
            passes. TrueScout uses statistical clustering on each position group to identify
            naturally occurring styles — grouping players whose statistical profiles look
            similar, independent of nationality or reputation.
          </Prose>
          <Prose>
            The &ldquo;Player Style&rdquo; label on each profile reflects which archetype cluster a
            player belongs to within their position group. The &ldquo;Similar Players&rdquo; section
            surfaces the highest-rated players in the same cluster.
          </Prose>
        </Card>

        {/* ── 7. Bracket simulation ─────────────────────────────────── */}
        <Card>
          <SectionHeader n={7} title="Bracket simulation" />
          <Prose>
            To forecast the knockout bracket, TrueScout runs <Em>100 000 Monte Carlo
            simulations</Em> — playing the tournament 100 000 times, each time sampling
            slightly different outcomes based on each team&apos;s estimated strength.
          </Prose>
          <Prose>
            Team strength is built from the bottom up: aggregate the player ratings of each
            nation&apos;s squad, weight by how much each player has featured, and adjust for squad
            depth. In each simulated match, the stronger team wins more often — but upsets
            happen at realistic rates, reflecting genuine tournament volatility.
          </Prose>
          <Callout>
            A team shown at <Em>34% to win the World Cup</Em> does not mean certainty — it
            means that in roughly 34 000 of the 100 000 simulations, that team lifted the
            trophy. The other 66 000 produced a different champion. Where bookmaker odds are
            available, we compare our win probabilities directly to highlight meaningful
            disagreements.
          </Callout>
        </Card>

        {/* ── 8. Track record ──────────────────────────────────────── */}
        <Card>
          <SectionHeader n={8} title="How we grade our predictions" />
          <Prose>
            After every completed match, we score our pre-match forecast using the{" "}
            <Em>Brier score</Em> — a standard accuracy metric where 0.00 is a perfect
            prediction and 0.25 is a coin flip. The lower, the better.
          </Prose>
          <Prose>
            We publish this openly on the{" "}
            <Link href="/brier" className="text-emerald-500 hover:text-emerald-400 transition-colors">
              Track Record
            </Link>{" "}
            page alongside the bookmakers&apos; implied probabilities, so you can see in real
            time whether the model is ahead of, behind, or in line with professional markets.
          </Prose>
          <Callout>
            We also track <Em>directional accuracy</Em> — how often our predicted favourite
            actually wins. This is the number most people find intuitive:{" "}
            {nMatches > 0
              ? <>of <Em>{nMatches}</Em> graded matches, the model correctly identified the winner <Em>{nCorrect}</Em> times.</>
              : <>once knockout matches are graded, we track how often the predicted favourite wins.</>
            }{" "}
            We show both because Brier score rewards getting the probability right, while
            directional accuracy rewards picking the right team. A model can be well-calibrated
            and still pick the wrong team in a 55/45 match.
          </Callout>
        </Card>

        {/* ── 9. Limitations ───────────────────────────────────────── */}
        <Card>
          <SectionHeader n={9} title="What the model cannot yet do" muted />
          <Prose>
            We believe in transparency. These are the real limitations of the current system:
          </Prose>
          <ul className="space-y-4">
            <LimitationItem title="Small World Cup sample">
              Many players have played only 2–4 matches in this tournament. The model leans
              heavily on club-season data to fill that gap, but club form does not always
              transfer — especially for players from leagues outside Europe&apos;s top five, where
              Understat coverage is absent.
            </LimitationItem>
            <LimitationItem title="Sofascore ratings are a black box">
              We use Sofascore match ratings as an input, but Sofascore does not publish how
              they compute them. Defensive contributions — a keeper making 8 saves in a 1–0
              win, a centre-back winning every aerial — tend to be systematically undervalued
              compared to goal-involvements.
            </LimitationItem>
            <LimitationItem title="No real-time injury or team-news feed">
              The model reflects the declared squad at last night&apos;s data pull. A player
              withdrawing the morning of a match will not affect the simulation until the
              next nightly update.
            </LimitationItem>
            <LimitationItem title="Penalty shootouts use a conservative prior">
              When a knockout match reaches extra time, the model gives the stronger
              team a 55 % advance probability (45 % to the weaker side) rather than
              pure 50/50. This reflects the modest historical edge the higher-rated side
              holds in shootouts. A shootout-specific model using actual penalty
              conversion records has not been built yet.
            </LimitationItem>
            <LimitationItem title="No tactical or manager signal">
              The model knows nothing about formations, pressing intensity, set-piece
              routines, or manager tendencies. Pure player-quality aggregates miss a
              meaningful share of what decides tight knockout matches.
            </LimitationItem>
            <LimitationItem title="Club data is Europe-only">
              Understat covers only the top five European leagues. Players from South
              America, Africa, Asia, and MLS are rated primarily on their World Cup
              performances, which means limited-minute players from those regions carry
              much higher uncertainty than their European counterparts.
            </LimitationItem>
          </ul>
        </Card>

      </div>

      {/* Footer */}
      <div className="flex items-center justify-between pt-2 border-t border-slate-800">
        <p className="text-xs text-slate-700">
          TrueScout · WC 2026 · Updated nightly at 02:00 UTC
        </p>
        <div className="flex items-center gap-4">
          <Link href="/players" className="text-xs text-slate-500 hover:text-slate-300 transition-colors">
            Player search →
          </Link>
          <Link href="/brier" className="text-xs text-emerald-500 hover:text-emerald-400 transition-colors">
            Track Record →
          </Link>
        </div>
      </div>

    </div>
  )
}
