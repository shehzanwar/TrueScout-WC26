import { getFlag, getFlagUrl } from "@/lib/flags"

export function FlagIcon({
  name,
  size = 20,
}: {
  name: string | null | undefined
  size?: number
}) {
  const url = getFlagUrl(name)
  if (url) {
    return (
      <img
        src={url}
        alt={name ?? ""}
        width={size}
        height={Math.round(size * 0.75)}
        className="inline-block rounded-[1px]"
        style={{ objectFit: "cover" }}
        loading="lazy"
      />
    )
  }
  const emoji = getFlag(name)
  return (
    <span
      role="img"
      aria-label={name ?? "flag"}
      style={{ fontSize: size * 0.9 }}
    >
      {emoji}
    </span>
  )
}
