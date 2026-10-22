// ヤタのカラス。体の色と小物を組み合わせて、ボットごとに見た目を変える。
import { CROW_ACCESSORIES, crowColor } from "../crow"

const ACC = "#F4B23A"
const ACC_DARK = "#B97F14"
const LINE = "#1B1226"

type CrowProps = {
  color?: string
  accessory?: string
  size?: number
  className?: string
  title?: string
  /** 後ろに日輪（八咫烏は太陽の使い）を出す */
  sun?: boolean
}

export function Crow({ color, accessory = "none", size = 112, className, title, sun = false }: CrowProps) {
  const c = crowColor(color)
  const a = accessory in CROW_ACCESSORIES ? accessory : "none"
  return (
    <svg
      viewBox="0 0 120 120"
      width={size}
      height={size}
      className={className}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    >
      {sun ? (
        <g aria-hidden="true">
          <circle cx="60" cy="60" r="57" fill="#F6D9CF" />
          <circle cx="60" cy="60" r="49" fill="#EE8E73" opacity="0.55" />
        </g>
      ) : null}
      <rect x="47" y="96" width="6" height="12" rx="3" fill={c.dark} />
      <rect x="67" y="96" width="6" height="12" rx="3" fill={c.dark} />
      <ellipse cx="47" cy="109" rx="10" ry="5" fill={c.dark} />
      <ellipse cx="73" cy="109" rx="10" ry="5" fill={c.dark} />
      <ellipse cx="25" cy="74" rx="10" ry="17" transform="rotate(18 25 74)" fill={c.dark} />
      <ellipse cx="95" cy="74" rx="10" ry="17" transform="rotate(-18 95 74)" fill={c.dark} />
      <path d="M52 30 C50 19 58 14 66 18 C62 20 61 24 63 28 Z" fill={c.body} />
      <path d="M48 31 C42 25 34 28 33 32 C38 31 42 33 45 36 Z" fill={c.body} />
      <ellipse cx="60" cy="64" rx="37" ry="38" fill={c.body} />
      <ellipse cx="60" cy="84" rx="28" ry="16" fill={c.dark} opacity="0.35" />
      {a === "scarf" ? (
        <g>
          <path d="M30 84 C45 94 75 94 90 84 L90 92 C75 102 45 102 30 92 Z" fill={ACC} />
          <path d="M70 94 L80 110 L70 108 L64 96 Z" fill={ACC} />
        </g>
      ) : null}
      <path d="M42 50 C44 47 49 46 52 48" fill="none" stroke={c.dark} strokeWidth="2.4" strokeLinecap="round" />
      <path d="M68 48 C71 46 76 47 78 50" fill="none" stroke={c.dark} strokeWidth="2.4" strokeLinecap="round" />
      <circle cx="47" cy="60" r="8" fill="#22123A" />
      <circle cx="73" cy="60" r="8" fill="#22123A" />
      <circle cx="49.5" cy="57" r="3" fill="#FFFFFF" />
      <circle cx="75.5" cy="57" r="3" fill="#FFFFFF" />
      <circle cx="45" cy="63.5" r="1.4" fill="#FFFFFF" />
      <circle cx="71" cy="63.5" r="1.4" fill="#FFFFFF" />
      <path d="M51 70 C55 66 65 66 69 70 C65 76 55 76 51 70 Z" fill="#F2667A" />
      {a === "glasses" ? (
        <g>
          <circle cx="47" cy="60" r="12" fill="none" stroke={LINE} strokeWidth="3" />
          <circle cx="73" cy="60" r="12" fill="none" stroke={LINE} strokeWidth="3" />
          <path d="M59 59 C60 57.5 60 57.5 61 59" fill="none" stroke={LINE} strokeWidth="3" strokeLinecap="round" />
        </g>
      ) : null}
      {a === "phones" ? (
        <g>
          <path d="M24 62 C24 30 96 30 96 62" fill="none" stroke={LINE} strokeWidth="6" strokeLinecap="round" />
          <rect x="16" y="54" width="14" height="22" rx="6" fill={ACC} />
          <rect x="90" y="54" width="14" height="22" rx="6" fill={ACC} />
        </g>
      ) : null}
      {a === "beret" ? (
        <g>
          <ellipse cx="54" cy="30" rx="27" ry="10" transform="rotate(-12 54 30)" fill={ACC} />
          <rect x="51" y="16" width="5" height="7" rx="2.5" fill={ACC} />
        </g>
      ) : null}
      {a === "bow" ? (
        <g>
          <path d="M60 97 L46 90 L46 104 Z" fill={ACC} />
          <path d="M60 97 L74 90 L74 104 Z" fill={ACC} />
          <circle cx="60" cy="97" r="4" fill={ACC_DARK} />
        </g>
      ) : null}
      {a === "leaf" ? (
        <g>
          <path d="M62 26 C62 14 74 8 84 10 C82 20 74 27 62 26 Z" fill="#4C9A5F" />
          <path d="M63 25 C69 20 74 16 80 13" fill="none" stroke="#2E6B3D" strokeWidth="1.6" strokeLinecap="round" />
        </g>
      ) : null}
    </svg>
  )
}
