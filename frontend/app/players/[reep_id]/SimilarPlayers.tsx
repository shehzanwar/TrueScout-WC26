import Link from "next/link"
import type { PlayerResponse } from "@/lib/api"
import FifaBadge from "../FifaBadge"
import { FlagIcon } from "@/app/components/FlagIcon"

// Map position_micro codes → readable plural form for the section subtitle
const _MICRO_LABEL: Record<string, string> = {
  GK: "Goalkeepers",
  CB: "Centre-Backs",
  LB: "Left-Backs",
  RB: "Right-Backs",
  WB: "Wing-Backs",
  DM: "Defensive Mids",
  CM: "Central Mids",
  AM: "Attacking Mids",
  LW: "Left Wingers",
  RW: "Right Wingers",
  SS: "Second Strikers",
  CF: "Strikers",
}

function groupLabel(player: PlayerResponse): string {
  if (player.cluster_label) return `${player.cluster_label}s`
  if (player.position_detail) return `${player.position_detail}s`
  if (player.position_micro && _MICRO_LABEL[player.position_micro])
    return _MICRO_LABEL[player.position_micro]
  const macro: Record<string, string> = {
    GK: "Goalkeepers", DEF: "Defenders", MID: "Midfielders", FWD: "Forwards",
  }
  return macro[player.position_macro] ?? "Players"
}

function positionLine(p: PlayerResponse): string {
  return p.position_detail ?? p.position_micro ?? p.position_macro ?? ""
}

export default function SimilarPlayers({
  current,
  players,
}: {
  current: PlayerResponse
  players: PlayerResponse[]
}) {
  if (players.length < 2) return null

  const subtitle = `${groupLabel(current)} at this World Cup · ranked by rating`

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
      <div className="mb-4">
        <h2 className="text-sm font-semibold text-slate-100 uppercase tracking-wider">
          Similar Players
        </h2>
        <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {players.map((p) => (
          <Link
            key={p.reep_id}
            href={`/players/${p.reep_id}`}
            className="group flex flex-col gap-1.5 p-3 rounded-lg bg-slate-800/40 hover:bg-slate-800 border border-slate-700/40 hover:border-slate-600 transition-colors"
          >
            {/* Nationality */}
            <div className="flex items-center gap-1.5 min-w-0">
              <FlagIcon name={p.national_team ?? p.nationality} size={14} />
              <span className="text-[11px] text-slate-500 truncate">
                {p.nationality ?? ""}
              </span>
            </div>

            {/* Name */}
            <span className="text-sm font-medium text-slate-100 group-hover:text-white leading-snug line-clamp-2 min-h-[2.5rem]">
              {p.name ?? p.reep_id}
            </span>

            {/* Position + rating */}
            <div className="flex items-end justify-between mt-auto gap-1">
              <span className="text-[11px] text-slate-600 truncate">
                {positionLine(p)}
              </span>
              {p.fifa ? (
                <FifaBadge fifa={p.fifa} size="sm" />
              ) : (
                <span className="text-xs font-bold tabular-nums text-slate-400">
                  {p.posterior_mean.toFixed(1)}
                </span>
              )}
            </div>
          </Link>
        ))}
      </div>
    </div>
  )
}
