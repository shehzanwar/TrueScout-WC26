import type { Metadata } from "next"
import { Geist, Geist_Mono } from "next/font/google"
import "./globals.css"
import Sidebar from "./components/Sidebar"
import SidebarClient from "./components/SidebarClient"
import StaleDataBanner from "./components/StaleDataBanner"
import { getSimulations } from "@/lib/server-data"

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
})

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
})

export const metadata: Metadata = {
  title: {
    default: "TrueScout — WC 2026 Intelligence",
    template: "%s · TrueScout",
  },
  description: "Monte Carlo bracket simulation and player ratings for the 2026 FIFA World Cup",
  metadataBase: new URL("https://truescout.vercel.app"),
  openGraph: {
    siteName: "TrueScout",
    type: "website",
    locale: "en_US",
    title: "TrueScout — WC 2026 Intelligence",
    description: "Monte Carlo bracket simulation and player ratings for the 2026 FIFA World Cup",
  },
  twitter: {
    card: "summary",
    title: "TrueScout — WC 2026 Intelligence",
    description: "Monte Carlo bracket simulation and player ratings for the 2026 FIFA World Cup",
  },
}

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const lastUpdated = await getSimulations().then(s => s.run_date).catch(() => undefined)
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-screen bg-slate-950">
        {/* Desktop sidebar — hidden on mobile */}
        <Sidebar lastUpdated={lastUpdated} />
        {/* Mobile: sticky top bar + slide-in drawer */}
        <div className="flex-1 min-w-0 flex flex-col">
          <SidebarClient />
          <main className="flex-1 min-w-0 p-6 lg:p-8">
            <StaleDataBanner runDate={lastUpdated} />
            {children}
          </main>
        </div>
      </body>
    </html>
  )
}
