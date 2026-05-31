import { useState, useEffect, useCallback } from 'react'
import icon1 from '../../../assets/images/icons/singularity.png'
import icon2 from '../../../assets/images/icons/oblivion.png'
import icon3 from '../../../assets/images/icons/eternity.png'

// ── Constants ──────────────────────────────────────────────────────────────────

export const PRESET_ICONS = [icon1, icon2, icon3] as const
export type PresetIcon    = typeof PRESET_ICONS[number]

const LS_ICON   = 'sentinel-user-icon'
const LS_CUSTOM = 'sentinel-custom-icon'

// icon index: 0 = initials | 1-3 = presets | 4 = custom upload
type IconIdx = 0 | 1 | 2 | 3 | 4

// ── Hook ───────────────────────────────────────────────────────────────────────

export type IconState = {
  idx:        number
  total:      number
  customSrc:  string | null
  currentSrc: string | null
  label:      string
  prev:       () => void
  next:       () => void
  upload:     (file: File) => void
  remove:     () => void
}

export function useIconState(
  setUserIcon: (url: string | undefined) => void
): IconState {
  const [idx,       setIdx]       = useState<IconIdx>(0)
  const [customSrc, setCustomSrc] = useState<string | null>(null)

  // Restore selection from localStorage on mount
  useEffect(() => {
    const stored = localStorage.getItem(LS_ICON)   ?? ''
    const custom = localStorage.getItem(LS_CUSTOM) ?? ''

    if (custom) setCustomSrc(custom)

    if (!stored) return
    const presetIdx = PRESET_ICONS.indexOf(stored as PresetIcon)
    if (presetIdx >= 0)           { setIdx((presetIdx + 1) as IconIdx); return }
    if (stored === custom && custom) { setIdx(4);                        return }
  }, [])

  const total = (customSrc ? 5 : 4) as number

  /** Apply an index, optionally supplying an in-flight custom src */
  const apply = useCallback((nextIdx: IconIdx, nextCustom?: string) => {
    setIdx(nextIdx)
    const src: string | undefined =
      nextIdx === 0 ? undefined :
      nextIdx <= 3  ? PRESET_ICONS[nextIdx - 1] :
      nextCustom ?? customSrc ?? undefined
    setUserIcon(src)
  }, [customSrc, setUserIcon])

  const prev = useCallback(
    () => apply(((idx - 1 + total) % total) as IconIdx),
    [apply, idx, total]
  )

  const next = useCallback(
    () => apply(((idx + 1) % total) as IconIdx),
    [apply, idx, total]
  )

  const upload = useCallback((file: File) => {
    const reader = new FileReader()
    reader.onload = ev => {
      const base64 = ev.target?.result as string
      localStorage.setItem(LS_CUSTOM, base64)
      setCustomSrc(base64)
      apply(4, base64)
    }
    reader.readAsDataURL(file)
  }, [apply])

  const remove = useCallback(() => {
    localStorage.removeItem(LS_CUSTOM)
    setCustomSrc(null)
    if (idx === 4) apply(0)
  }, [apply, idx])

  const currentSrc: string | null =
    idx === 0 ? null :
    idx <= 3  ? PRESET_ICONS[idx - 1] :
    customSrc

  const label =
    idx === 0 ? 'Initials' :
    idx <= 3  ? `Icon ${idx}` :
    'Custom'

  return { idx, total, customSrc, currentSrc, label, prev, next, upload, remove }
}
