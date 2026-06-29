"use client"

import { useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { generateNarrative, type NarrativeResponse } from "@/lib/api"

type Status = "idle" | "loading" | "done" | "error"

function VoiceBadge({ voice }: { voice: NarrativeResponse["voice"] }) {
  if (voice === "data_analyst") {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
        Data Analyst
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-500/15 text-amber-400 border border-amber-500/20">
      <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
      Traditional Scout
    </span>
  )
}

export default function TacticalAnalysis({ reepId }: { reepId: string }) {
  const [status, setStatus]   = useState<Status>("idle")
  const [result, setResult]   = useState<NarrativeResponse | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  async function handleGenerate() {
    setStatus("loading")
    setErrorMsg(null)
    try {
      const data = await generateNarrative(reepId)
      setResult(data)
      setStatus("done")
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : null)
      setStatus("error")
    }
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div>
          <h2 className="text-sm font-semibold text-slate-100 uppercase tracking-wider">
            Tactical Analysis
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            AI-generated scouting report · OpenRouter RAG
          </p>
        </div>
        <AnimatePresence mode="wait">
          {status === "done" && result ? (
            <motion.div
              key="badge"
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9 }}
              transition={{ duration: 0.2 }}
            >
              <VoiceBadge voice={result.voice} />
            </motion.div>
          ) : (
            <motion.span
              key="model"
              initial={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="text-xs text-slate-600 border border-slate-800 px-2.5 py-1 rounded-full"
            >
              {status === "loading" ? "Generating…" : "Nemotron 3 Ultra · OpenRouter"}
            </motion.span>
          )}
        </AnimatePresence>
      </div>

      {/* Body */}
      <AnimatePresence mode="wait">
        {status === "idle" && (
          <motion.div
            key="idle"
            initial={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="space-y-2.5"
          >
            {[80, 95, 88, 72, 60].map((w, i) => (
              <div
                key={i}
                className="h-3 bg-slate-800 rounded"
                style={{ width: `${w}%` }}
              />
            ))}
          </motion.div>
        )}

        {status === "loading" && (
          <motion.div
            key="loading"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="space-y-2.5"
          >
            {[80, 95, 88, 72, 60].map((w, i) => (
              <div
                key={i}
                className="h-3 bg-slate-800 rounded animate-pulse"
                style={{ width: `${w}%`, animationDelay: `${i * 80}ms` }}
              />
            ))}
          </motion.div>
        )}

        {status === "done" && result && (
          <motion.div
            key="narrative"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: "easeOut" as const }}
            className="space-y-3"
          >
            {result.narrative.split("\n\n").filter(Boolean).map((para, i) => (
              <motion.p
                key={i}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: i * 0.08, ease: "easeOut" as const }}
                className="text-sm text-slate-300 leading-relaxed"
              >
                {para.trim()}
              </motion.p>
            ))}
          </motion.div>
        )}

        {status === "error" && (
          <motion.div
            key="error"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="py-4 space-y-3"
          >
            <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/20 text-xs text-amber-400">
              <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4 shrink-0 mt-0.5">
                <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 0 1 .75.75v3.5a.75.75 0 0 1-1.5 0v-3.5A.75.75 0 0 1 10 5zm0 9a1 1 0 1 0 0-2 1 1 0 0 0 0 2z" clipRule="evenodd" />
              </svg>
              <span>
                AI Analyst unavailable{errorMsg ? `: ${errorMsg}` : ""}
              </span>
            </div>
            <button
              onClick={handleGenerate}
              className="text-xs text-slate-500 underline hover:text-slate-300 transition-colors"
            >
              Try again
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Generate button */}
      <AnimatePresence>
        {(status === "idle" || status === "error") && (
          <motion.button
            key="btn"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={handleGenerate}
            className="mt-5 w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg border border-emerald-500/30 bg-emerald-500/5 hover:bg-emerald-500/10 hover:border-emerald-500/50 text-sm text-emerald-400 transition-all duration-150 cursor-pointer"
          >
            <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
              <path d="M10 2a.75.75 0 0 1 .75.75v.258a33.186 33.186 0 0 1 6.668 2.373.75.75 0 1 1-.636 1.351 31.665 31.665 0 0 0-6.032-2.171V10.5a1 1 0 0 1-2 0V4.561a31.67 31.67 0 0 0-6.032 2.17.75.75 0 0 1-.636-1.35A33.19 33.19 0 0 1 9.25 3.008V2.75A.75.75 0 0 1 10 2Z" />
            </svg>
            Generate Scouting Report
          </motion.button>
        )}
      </AnimatePresence>
    </div>
  )
}
