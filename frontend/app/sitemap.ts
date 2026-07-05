import type { MetadataRoute } from "next"
import { getNationSlugs } from "@/lib/server-data"
import { readFileSync } from "fs"
import path from "path"
import type { PlayerResponse } from "@/lib/api"

const BASE = "https://truescout.vercel.app"

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const staticRoutes: MetadataRoute.Sitemap = [
    { url: BASE,               priority: 1.0, changeFrequency: "daily" },
    { url: `${BASE}/bracket`,  priority: 0.9, changeFrequency: "daily" },
    { url: `${BASE}/matchups`, priority: 0.9, changeFrequency: "daily" },
    { url: `${BASE}/nations`,  priority: 0.8, changeFrequency: "daily" },
    { url: `${BASE}/players`,  priority: 0.8, changeFrequency: "daily" },
    { url: `${BASE}/compare`,  priority: 0.6, changeFrequency: "weekly" },
    { url: `${BASE}/brier`,    priority: 0.6, changeFrequency: "daily" },
  ]

  const nationSlugs = await getNationSlugs().catch(() => [] as string[])
  const nationRoutes: MetadataRoute.Sitemap = nationSlugs.map((slug) => ({
    url: `${BASE}/nations/${slug}`,
    priority: 0.7,
    changeFrequency: "daily",
  }))

  let playerRoutes: MetadataRoute.Sitemap = []
  try {
    const players = JSON.parse(
      readFileSync(path.join(process.cwd(), "public", "data", "players_lite.json"), "utf-8")
    ) as PlayerResponse[]
    playerRoutes = players
      .filter((p) => (p.wc_minutes ?? 0) > 0)
      .map((p) => ({
        url: `${BASE}/players/${p.reep_id}`,
        priority: 0.5,
        changeFrequency: "weekly" as const,
      }))
  } catch { /* players data may not exist during build */ }

  return [...staticRoutes, ...nationRoutes, ...playerRoutes]
}
