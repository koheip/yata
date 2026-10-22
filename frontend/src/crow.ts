// カラスの色と小物。ボットごとの見た目に使う。

export const CROW_COLORS = {
  purple: { label: "江戸紫", body: "#4B3170", dark: "#341F52", soft: "#ECE5F5" },
  blue: { label: "藍", body: "#2F5DA8", dark: "#213F75", soft: "#E3ECF8" },
  green: { label: "松葉", body: "#2F6B4F", dark: "#204A37", soft: "#E2F0E8" },
  orange: { label: "柿", body: "#C0662B", dark: "#88461C", soft: "#F8E8DD" },
  pink: { label: "牡丹", body: "#B4487B", dark: "#803156", soft: "#F6E3EC" },
  gray: { label: "鈍", body: "#5A5466", dark: "#3D3947", soft: "#ECEAF0" },
} as const

export const CROW_ACCESSORIES = {
  none: "なし",
  phones: "ヘッドホン",
  glasses: "メガネ",
  beret: "ベレー帽",
  bow: "蝶ネクタイ",
  scarf: "マフラー",
  leaf: "葉っぱ",
} as const

export type CrowColor = keyof typeof CROW_COLORS
export type CrowAccessory = keyof typeof CROW_ACCESSORIES

export function isCrowColor(value: string | undefined): value is CrowColor {
  return value !== undefined && value in CROW_COLORS
}

export function crowColor(value: string | undefined) {
  return CROW_COLORS[isCrowColor(value) ? value : "purple"]
}


/** まだ誰も使っていない「色 × 小物」を選ぶ。全部使っていたら重なってもよい。 */
export function pickLook(used: { color: string; accessory: string }[], avoid?: { color: string; accessory: string }) {
  const taken = new Set(used.map((look) => `${look.color}/${look.accessory}`))
  if (avoid) taken.add(`${avoid.color}/${avoid.accessory}`)
  const free: { color: string; accessory: string }[] = []
  for (const color of Object.keys(CROW_COLORS)) {
    for (const accessory of Object.keys(CROW_ACCESSORIES)) {
      if (!taken.has(`${color}/${accessory}`)) free.push({ color, accessory })
    }
  }
  if (free.length === 0) return { color: "purple", accessory: "none" }
  return free[Math.floor(Math.random() * free.length)]
}
