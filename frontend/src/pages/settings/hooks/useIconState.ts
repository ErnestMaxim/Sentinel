import { useState, useEffect } from 'react'
import icon1 from '../../../assets/images/icons/singularity.png'
import icon2 from '../../../assets/images/icons/oblivion.png'
import icon3 from '../../../assets/images/icons/eternity.png'

// ── Constants ─────────────────────────────────────────────────────────────────

export const PRESET_ICONS = [icon1, icon2, icon3] as const
export type PresetIcon    = typeof PRESET_ICONS[number]

const LS_ICON   = 'sentinel-user-icon'
const LS_CUSTOM = 'sentinel-custom-icon'

// icon index: 0 = initials | 1-3 = presets | 4 = custom upload
type IconIdx = 0 | 1 | 2 | 3 | 4

// ── Types ─────────────────────────────────────────────────────────────────────

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

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useIconState(
  setUserIcon: (url: string | undefined) => void
): IconState {
  const [idx,       setIdx]       = useState<IconIdx>(0)
  const [customSrc, setCustomSrc] = useState<string | null>(null)
  
  useEffect(() => {
    const stored = localStorage.getItem(LS_ICON)   ?? ''
    const custom = localStorage.getItem(LS_CUSTOM) ?? ''

    const presetIdx = PRESET_ICONS.indexOf(stored as PresetIcon)
    if (presetIdx >= 0) {
      setIdx((presetIdx + 1) as IconIdx)
      return
    }

    if (stored && stored === custom) {
      setCustomSrc(custom)
      setIdx(4)
      return
    }

    setCustomSrc(null)
    setIdx(0)
  }, [])

  const total = (customSrc ? 5 : 4) as number

  function apply(nextIdx: IconIdx, nextCustom?: string) {
    setIdx(nextIdx)
    const src: string | undefined =
      nextIdx === 0 ? undefined :
      nextIdx <= 3  ? PRESET_ICONS[nextIdx - 1] :
      nextCustom ?? customSrc ?? undefined
    setUserIcon(src)
  }

  function resizeToBase64(file: File, maxPx = 256): Promise<string> {
    return new Promise((resolve, reject) => {
      const img = new Image()
      const url = URL.createObjectURL(file)
      img.onload = () => {
        URL.revokeObjectURL(url)
        const scale = Math.min(1, maxPx / Math.max(img.width, img.height))
        const w = Math.round(img.width  * scale)
        const h = Math.round(img.height * scale)
        const canvas = document.createElement('canvas')
        canvas.width  = w
        canvas.height = h
        canvas.getContext('2d')!.drawImage(img, 0, 0, w, h)
        resolve(canvas.toDataURL('image/jpeg', 0.82))
      }
      img.onerror = reject
      img.src = url
    })
  }

  function prev() { apply(((idx - 1 + total) % total) as IconIdx) }
  function next() { apply(((idx + 1) % total) as IconIdx) }

  function upload(file: File) {
    resizeToBase64(file).then(base64 => {
      localStorage.setItem(LS_CUSTOM, base64)
      localStorage.setItem(LS_ICON,   base64)
      setCustomSrc(base64)
      setIdx(4)
      setUserIcon(base64)
    })
  }

  function remove() {
    localStorage.removeItem(LS_CUSTOM)
    setCustomSrc(null)
    if (idx === 4) apply(0)
  }

  const currentSrc: string | null =
    idx === 0 ? null :
    idx <= 3  ? PRESET_ICONS[idx - 1] :
    customSrc

  const label =
    idx === 0 ? 'Initials' :
    idx <= 3  ? `Preset ${idx}` :
    'Custom'

  return { idx, total, customSrc, currentSrc, label, prev, next, upload, remove }
}