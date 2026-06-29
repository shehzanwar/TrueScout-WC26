import type { Metadata } from "next"
import { Geist, Geist_Mono } from "next/font/google"
import "./globals.css"
import Sidebar from "./components/Sidebar"

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
})

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
})

export const metadata: Metadata = {
  title: "TrueScout — WC 2026 Intelligence",
  description: "Monte Carlo bracket simulation and player ratings for the 2026 FIFA World Cup",
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-screen bg-slate-950">
        <Sidebar />
        <main className="flex-1 min-w-0 p-6 lg:p-8">{children}</main>
      </body>
    </html>
  )
}
