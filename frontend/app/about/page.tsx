import Link from "next/link"

export default function AboutPage() {
  return (
    <div className="max-w-2xl mx-auto space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-100">How TrueScout Works</h1>
        <p className="mt-1 text-sm text-slate-500">
          A plain-English guide — no maths degree required
        </p>
      </div>

      <div className="space-y-4">
        {/* Section 1 */}
        <section className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-3">
          <div className="flex items-center gap-2">
            <span className="w-6 h-6 rounded-full bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center text-emerald-400 text-xs font-bold shrink-0">
              1
            </span>
            <h2 className="text-base font-semibold text-slate-100">How the rating works</h2>
          </div>
          <p className="text-sm text-slate-400 leading-relaxed">
            We combine two years of club performance with World Cup results using a statistical
            technique called Bayesian shrinkage. Think of it as a weighted average: when a player
            has played a lot of World Cup minutes, we trust that data more. When they&apos;ve barely
            featured, we lean on their club track record instead. The rating reflects how good a
            player is <span className="text-slate-200 font-medium">right now</span>, not their
            career average. Stronger opponents count for more — a 7.5 against France matters more
            than the same score against a weaker side.
          </p>
        </section>

        {/* Section 2 */}
        <section className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-3">
          <div className="flex items-center gap-2">
            <span className="w-6 h-6 rounded-full bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center text-emerald-400 text-xs font-bold shrink-0">
              2
            </span>
            <h2 className="text-base font-semibold text-slate-100">What data confidence means</h2>
          </div>
          <p className="text-sm text-slate-400 leading-relaxed">
            The confidence indicator tells you how much data backs up a player&apos;s rating. A green
            badge means we have plenty of recent match data and the estimate is solid. Amber means
            partial data — the rating is reasonable but a bit uncertain. Red means the player has
            barely played, so treat the rating as a rough guide rather than a firm verdict.
          </p>
          <div className="flex flex-wrap gap-2.5 pt-1">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
              High — reliable estimate
            </span>
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-500/15 text-amber-400 border border-amber-500/20">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
              Moderate — some uncertainty
            </span>
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-rose-500/15 text-rose-400 border border-rose-500/20">
              <span className="w-1.5 h-1.5 rounded-full bg-rose-400 shrink-0" />
              Sparse — limited data
            </span>
          </div>
        </section>

        {/* Section 3 */}
        <section className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-3">
          <div className="flex items-center gap-2">
            <span className="w-6 h-6 rounded-full bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center text-emerald-400 text-xs font-bold shrink-0">
              3
            </span>
            <h2 className="text-base font-semibold text-slate-100">How predictions are graded</h2>
          </div>
          <p className="text-sm text-slate-400 leading-relaxed">
            After each match, we score our pre-match predictions using{" "}
            <span className="text-slate-200 font-medium">Prediction Accuracy</span> (also called
            Brier Score) — a standard measure where lower is better and a random coin-flip scores
            0.25. We compare against professional bookmakers to find where our model has an edge.
            When TrueScout gives a team a meaningfully higher probability than the bookies, we flag
            it as a <span className="text-slate-200 font-medium">value pick</span>. The{" "}
            <Link href="/brier" className="text-emerald-500 hover:text-emerald-400 transition-colors">
              Model Calibration
            </Link>{" "}
            page tracks accuracy in real time as the tournament progresses.
          </p>
        </section>
        {/* Section 4 — Critique */}
        <section className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
          <div className="flex items-center gap-2">
            <span className="w-6 h-6 rounded-full bg-slate-700/60 border border-slate-600/40 flex items-center justify-center text-slate-400 text-xs font-bold shrink-0">
              4
            </span>
            <h2 className="text-base font-semibold text-slate-100">What our model can&apos;t yet capture</h2>
          </div>
          <p className="text-sm text-slate-500 leading-relaxed">
            We believe in transparency. Here are the real limitations of the current system:
          </p>
          <ul className="space-y-3">
            <li className="flex gap-3">
              <span className="mt-0.5 w-1.5 h-1.5 rounded-full bg-slate-600 shrink-0 mt-[7px]" />
              <div>
                <p className="text-sm text-slate-300 font-medium">Small World Cup sample</p>
                <p className="text-xs text-slate-500 leading-relaxed mt-0.5">
                  Many players have played only 2–4 matches in this tournament. The model leans
                  heavily on club-season data to fill that gap, but club form doesn&apos;t always
                  transfer — especially for players from leagues outside Europe&apos;s top five.
                </p>
              </div>
            </li>
            <li className="flex gap-3">
              <span className="mt-0.5 w-1.5 h-1.5 rounded-full bg-slate-600 shrink-0 mt-[7px]" />
              <div>
                <p className="text-sm text-slate-300 font-medium">Sofascore ratings are a black box</p>
                <p className="text-xs text-slate-500 leading-relaxed mt-0.5">
                  We use Sofascore match ratings as an input, but Sofascore doesn&apos;t publish how
                  they compute them. A keeper who makes 8 saves in a 1–0 win may rate lower than a
                  striker who scores in a 4–0 win — the defensive contribution is underweighted in
                  their algorithm.
                </p>
              </div>
            </li>
            <li className="flex gap-3">
              <span className="mt-0.5 w-1.5 h-1.5 rounded-full bg-slate-600 shrink-0 mt-[7px]" />
              <div>
                <p className="text-sm text-slate-300 font-medium">No injury or squad news feed</p>
                <p className="text-xs text-slate-500 leading-relaxed mt-0.5">
                  If a key player picks up an injury after the nightly export runs, the model won&apos;t
                  know until the next update. Team strength estimates reflect the declared squad, not
                  real-time availability.
                </p>
              </div>
            </li>
            <li className="flex gap-3">
              <span className="mt-0.5 w-1.5 h-1.5 rounded-full bg-slate-600 shrink-0 mt-[7px]" />
              <div>
                <p className="text-sm text-slate-300 font-medium">Penalty shootouts are 50/50</p>
                <p className="text-xs text-slate-500 leading-relaxed mt-0.5">
                  For matches that go to penalties, the simulation currently gives each team an equal
                  coin-flip chance. Penalty conversion records exist in the data, but we haven&apos;t
                  built that model yet.
                </p>
              </div>
            </li>
            <li className="flex gap-3">
              <span className="mt-0.5 w-1.5 h-1.5 rounded-full bg-slate-600 shrink-0 mt-[7px]" />
              <div>
                <p className="text-sm text-slate-300 font-medium">No tactical or manager signal</p>
                <p className="text-xs text-slate-500 leading-relaxed mt-0.5">
                  The model knows nothing about formations, pressing intensity, set-piece routines, or
                  whether a manager tends to out-prepare a particular opponent. Pure player-quality
                  aggregates miss a meaningful share of what decides tight knockout matches.
                </p>
              </div>
            </li>
          </ul>
        </section>
      </div>

      {/* Footer links */}
      <div className="flex items-center justify-between pt-2 border-t border-slate-800">
        <p className="text-xs text-slate-700">
          TrueScout · WC 2026 · Bayesian player intelligence
        </p>
        <Link
          href="/brier"
          className="text-xs text-emerald-500 hover:text-emerald-400 transition-colors"
        >
          View model accuracy →
        </Link>
      </div>
    </div>
  )
}
