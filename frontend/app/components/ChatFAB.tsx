"use client"
import { useState } from "react"
import dynamic from "next/dynamic"

const ChatModal = dynamic(() => import("./ChatModal"), { ssr: false })

export default function ChatFAB() {
  const [open, setOpen] = useState(false)

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        aria-label="Ask TrueScout AI"
        className="fixed bottom-6 right-6 z-40 w-13 h-13 rounded-full bg-emerald-600 hover:bg-emerald-500 shadow-lg shadow-emerald-900/40 flex items-center justify-center text-xl transition-all hover:scale-105 active:scale-95"
        style={{ width: "3.25rem", height: "3.25rem" }}
      >
        ⚽
      </button>
      {open && <ChatModal onClose={() => setOpen(false)} />}
    </>
  )
}
