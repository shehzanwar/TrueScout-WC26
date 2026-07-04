import { ImageResponse } from "next/og"
import { getPlayer } from "@/lib/server-data"

export const size = { width: 1200, height: 630 }
export const contentType = "image/png"

export default async function Image({
  params,
}: {
  params: Promise<{ reep_id: string }>
}) {
  const { reep_id } = await params
  const player = await getPlayer(reep_id).catch(() => null)

  const name     = player?.name ?? "Player"
  const position = player?.position_detail ?? player?.position_micro ?? player?.position_macro ?? ""
  const nat      = player?.nationality ?? ""
  const rating   = player?.posterior_mean != null ? player.posterior_mean.toFixed(2) : "—"
  const subline  = [nat, position].filter(Boolean).join(" · ")

  return new ImageResponse(
    (
      <div
        style={{
          background: "#0f172a",
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-start",
          justifyContent: "center",
          padding: "64px 80px",
          fontFamily: "sans-serif",
        }}
      >
        {/* Brand label */}
        <div
          style={{
            color: "#10b981",
            fontSize: 22,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            marginBottom: 36,
          }}
        >
          TrueScout · WC 2026
        </div>

        {/* Player name */}
        <div
          style={{
            color: "#f1f5f9",
            fontSize: name.length > 22 ? 56 : 68,
            fontWeight: 800,
            lineHeight: 1.05,
            marginBottom: 20,
          }}
        >
          {name}
        </div>

        {/* Nationality · Position */}
        {subline && (
          <div style={{ color: "#64748b", fontSize: 28, marginBottom: 40 }}>
            {subline}
          </div>
        )}

        {/* Rating */}
        <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
          <span style={{ color: "#10b981", fontSize: 76, fontWeight: 800 }}>
            {rating}
          </span>
          <span style={{ color: "#475569", fontSize: 34 }}>/10</span>
        </div>
      </div>
    ),
    { width: 1200, height: 630 },
  )
}
