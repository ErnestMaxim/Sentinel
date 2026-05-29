// ── constants.ts ──────────────────────────────────────────────────────────────

export const PW = 210
export const PH = 297
export const ML = 22
export const MR = 22
export const MT = 20
export const CW = PW - ML - MR

export const LINE_H     = 4.4
export const FONT_TINY  = 6.0
export const FONT_SMALL = 7.0
export const FONT_BODY  = 8.0
export const FONT_SUB   = 9.5
export const FONT_HEAD  = 13.0
export const FONT_TITLE = 26.0

export type RGB = [number, number, number]

export const C: Record<string, RGB> = {
  // Base
  pageBg:    [255, 255, 255],
  cardBg:    [250, 250, 252],
  border:    [230, 230, 235],
  borderSoft:[242, 242, 245],

  // Text
  textMain:  [18,  18,  24],
  textMuted: [120, 120, 135],
  textDim:   [175, 175, 188],

  // Brand
  yellow:    [255, 210,   0],
  yellowBg:  [255, 249, 220],
  yellowText:[140, 110,   0],

  // Semantic — muted, not loud
  red:       [210,  60,  60],
  redBg:     [255, 245, 245],
  redMuted:  [240, 200, 200],

  purple:    [120,  70, 210],
  purpleBg:  [248, 244, 255],
  purpleMuted:[210,195,240],

  green:     [40,  170,  90],
  greenBg:   [242, 253, 247],
  greenMuted:[180, 225, 200],

  orange:    [210, 120,  20],
  orangeBg:  [255, 248, 238],
  orangeMuted:[240,205,160],

  white:     [255, 255, 255],
  black:     [0,   0,   0],
}

export function scoreColor(pct: number): RGB {
  if (pct <= 15) return C.green
  if (pct <= 40) return C.orange
  return C.red
}

export function scoreBgColor(pct: number): RGB {
  if (pct <= 15) return C.greenBg
  if (pct <= 40) return C.orangeBg
  return C.redBg
}

export function scoreMutedColor(pct: number): RGB {
  if (pct <= 15) return C.greenMuted
  if (pct <= 40) return C.orangeMuted
  return C.redMuted
}