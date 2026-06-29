"use client"

import { useState, useRef } from "react"
import { motion, AnimatePresence } from "framer-motion"

interface TooltipProps {
  content: string
  children: React.ReactNode
}

export default function Tooltip({ content, children }: TooltipProps) {
  const [visible, setVisible] = useState(false)
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  function show() {
    if (hideTimer.current) clearTimeout(hideTimer.current)
    setVisible(true)
  }

  function hide() {
    hideTimer.current = setTimeout(() => setVisible(false), 120)
  }

  return (
    <span
      className="relative inline-flex items-center"
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
      onClick={() => setVisible((v) => !v)}
    >
      {children}
      <AnimatePresence>
        {visible && (
          <motion.div
            role="tooltip"
            initial={{ opacity: 0, y: -4, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.96 }}
            transition={{ duration: 0.14 }}
            className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2.5 z-50 w-56 bg-slate-800 border border-emerald-500/20 rounded-lg px-3 py-2 text-xs text-slate-300 shadow-xl shadow-black/40 pointer-events-none"
          >
            {content}
            <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-slate-800" />
          </motion.div>
        )}
      </AnimatePresence>
    </span>
  )
}

// Inline info icon — wrap a label in <LabelWithInfo> to get a ⓘ that triggers the tooltip
export function LabelWithInfo({ label, tip }: { label: string; tip: string }) {
  return (
    <Tooltip content={tip}>
      <span className="inline-flex items-center gap-1 cursor-default select-none">
        {label}
        <svg
          viewBox="0 0 16 16"
          fill="currentColor"
          className="w-3 h-3 text-slate-600 hover:text-slate-400 transition-colors shrink-0"
        >
          <path
            fillRule="evenodd"
            d="M15 8A7 7 0 1 1 1 8a7 7 0 0 1 14 0ZM9 5a1 1 0 1 1-2 0 1 1 0 0 1 2 0ZM6.75 8a.75.75 0 0 0 0 1.5h.75v1.75a.75.75 0 0 0 1.5 0V8.75A.75.75 0 0 0 8.25 8h-1.5Z"
            clipRule="evenodd"
          />
        </svg>
      </span>
    </Tooltip>
  )
}
