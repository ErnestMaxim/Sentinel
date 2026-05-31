/**
 * PdfViewer.tsx
 *
 * Renders an uploaded PDF page-by-page using PDF.js (loaded from CDN).
 * Exact copied phrases are highlighted by drawing semi-transparent red
 * rectangles on an overlay canvas positioned above each page's PDF canvas.
 * This canvas-based approach is reliable regardless of PDF.js text-layer
 * internals — the highlights are guaranteed to be visible.
 */
import { useEffect, useRef, useState } from 'react'
import styles from './PdfViewer.module.css'

// ── Public types ───────────────────────────────────────────────────────────────

export interface PhraseEntry {
  phrase:    string
  sourceIdx: number
  isExact:   boolean   // true = exact copy (red), false = paraphrase (purple)
}

interface Props {
  pdfUrl:        string
  authToken:     string | null
  phrases:       PhraseEntry[]
  onPhraseClick: (sourceIdx: number) => void
}

// ── PDF.js CDN loader (cached) ─────────────────────────────────────────────────

const PDFJS_VER  = '3.11.174'
const PDFJS_BASE = `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/${PDFJS_VER}`
let   pdfjsCache: any = null

function loadPdfJs(): Promise<any> {
  if (pdfjsCache) return Promise.resolve(pdfjsCache)
  if ((window as any).pdfjsLib) {
    pdfjsCache = (window as any).pdfjsLib
    pdfjsCache.GlobalWorkerOptions.workerSrc = `${PDFJS_BASE}/pdf.worker.min.js`
    return Promise.resolve(pdfjsCache)
  }
  return new Promise((resolve, reject) => {
    const s    = document.createElement('script')
    s.src      = `${PDFJS_BASE}/pdf.min.js`
    s.async    = true
    s.onload   = () => {
      const lib = (window as any).pdfjsLib
      lib.GlobalWorkerOptions.workerSrc = `${PDFJS_BASE}/pdf.worker.min.js`
      pdfjsCache = lib
      resolve(lib)
    }
    s.onerror = () => reject(new Error('Failed to load PDF.js'))
    document.head.appendChild(s)
  })
}

// ── Canvas highlight drawing ───────────────────────────────────────────────────

interface TextItem {
  str:       string
  transform: number[]   // PDF transform matrix [a,b,c,d,tx,ty]
  width:     number     // in PDF user-space units
  height:    number
}

/**
 * Draws semi-transparent red rectangles on `overlayCanvas` for every
 * occurrence of every phrase found in the page's text content.
 *
 * Uses `viewport.convertToViewportPoint` to map PDF user-space coordinates
 * to canvas pixel coordinates.
 */
// Highlight colours
const EXACT_COLOR     = 'rgba(220, 38,  38,  0.38)'   // red
const PARA_COLOR      = 'rgba(124, 58,  237, 0.30)'   // purple

function drawHighlights(
  overlayCanvas: HTMLCanvasElement,
  viewport:      any,
  textItems:     TextItem[],
  phrases:       PhraseEntry[],
): Map<number, number> /* charOffset → sourceIdx */ {

  const ctx = overlayCanvas.getContext('2d')!
  ctx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height)

  // Build full-text string with item offset map
  let fullText = ''
  const ranges: { start: number; end: number; item: TextItem }[] = []
  for (const item of textItems) {
    if (!item.str) continue
    ranges.push({ start: fullText.length, end: fullText.length + item.str.length, item })
    fullText += item.str
  }
  if (!fullText) return new Map()

  const lower = fullText.toLowerCase()

  // Find all phrase positions, storing isExact per match
  interface Match { start: number; end: number; sourceIdx: number; isExact: boolean }
  const matches: Match[] = []
  for (const { phrase, sourceIdx, isExact } of phrases) {
    const ph = phrase.toLowerCase().trim()
    if (ph.length < 6) continue
    let pos = 0
    while (pos < lower.length) {
      const idx = lower.indexOf(ph, pos)
      if (idx === -1) break
      matches.push({ start: idx, end: idx + ph.length, sourceIdx, isExact })
      pos = idx + ph.length
    }
  }
  if (matches.length === 0) return new Map()

  // char → sourceIdx map for click detection
  const charSourceMap = new Map<number, number>()
  for (const m of matches) {
    for (let i = m.start; i < m.end; i++) charSourceMap.set(i, m.sourceIdx)
  }

  // Draw highlights — exact = red, paraphrase = purple
  for (const match of matches) {
    ctx.fillStyle = match.isExact ? EXACT_COLOR : PARA_COLOR

    for (const range of ranges) {
      if (range.end <= match.start || range.start >= match.end) continue

      const [a, b, , , tx, ty] = range.item.transform
      const [cx, cy] = viewport.convertToViewportPoint(tx, ty)
      const itemW    = Math.abs(range.item.width) * viewport.scale
      const fontH    = Math.sqrt(a * a + b * b) * viewport.scale

      if (itemW < 1 || fontH < 1) continue
      ctx.fillRect(cx, cy - fontH, itemW, fontH * 1.25)
    }
  }

  return charSourceMap
}

// ── Component ──────────────────────────────────────────────────────────────────

export default function PdfViewer({ pdfUrl, authToken, phrases, onPhraseClick }: Props) {
  const wrapRef                    = useRef<HTMLDivElement>(null)
  const [status, setStatus]        = useState<'loading' | 'error' | 'done'>('loading')
  const [errorMsg, setErrorMsg]    = useState('')
  const [progress, setProgress]    = useState({ n: 0, total: 0 })

  useEffect(() => {
    if (!pdfUrl) return
    let cancelled = false

    async function run() {
      setStatus('loading')
      setErrorMsg('')
      const wrap = wrapRef.current
      if (!wrap) return
      wrap.innerHTML = ''

      try {
        // Load PDF.js
        const lib = await loadPdfJs()
        if (cancelled) return

        // Fetch the PDF with auth header
        const res = await fetch(pdfUrl, {
          headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
        })
        if (!res.ok) throw new Error(`Server returned ${res.status}`)
        const buf = await res.arrayBuffer()
        if (cancelled) return

        // Parse PDF
        const pdfDoc = await lib.getDocument({ data: buf }).promise
        if (cancelled) return

        const total = pdfDoc.numPages
        setProgress({ n: 0, total })

        const SCALE = 1.5   // rendering scale (higher = crisper, slower)

        for (let pn = 1; pn <= total; pn++) {
          if (cancelled) return

          const page     = await pdfDoc.getPage(pn)
          const viewport = page.getViewport({ scale: SCALE })
          const W        = Math.floor(viewport.width)
          const H        = Math.floor(viewport.height)

          // ── Page shell ──────────────────────────────────────────────
          const shell     = document.createElement('div')
          shell.className = styles.pageShell
          shell.style.width  = W + 'px'
          shell.style.height = H + 'px'
          wrap.appendChild(shell)

          // ── 1. PDF canvas (bottom layer) ─────────────────────────────
          const pdfCanvas    = document.createElement('canvas')
          pdfCanvas.width    = W
          pdfCanvas.height   = H
          pdfCanvas.className = styles.pdfCanvas
          shell.appendChild(pdfCanvas)

          const pdfCtx = pdfCanvas.getContext('2d')!
          await page.render({ canvasContext: pdfCtx, viewport }).promise
          if (cancelled) return

          // ── 2. Get text content ──────────────────────────────────────
          const textContent = await page.getTextContent()
          if (cancelled) return
          const textItems = (textContent.items ?? []) as TextItem[]

          // ── 3. Highlight overlay canvas (middle layer) ───────────────
          if (phrases.length > 0 && textItems.length > 0) {
            const hlCanvas    = document.createElement('canvas')
            hlCanvas.width    = W
            hlCanvas.height   = H
            hlCanvas.className = styles.hlCanvas
            shell.appendChild(hlCanvas)

            const charSourceMap = drawHighlights(hlCanvas, viewport, textItems, phrases)

            // Click on highlight → scroll to source detail
            if (charSourceMap.size > 0) {
              hlCanvas.addEventListener('click', (e) => {
                const rect = hlCanvas.getBoundingClientRect()
                const mx   = (e.clientX - rect.left) * (W / rect.width)
                const my   = (e.clientY - rect.top)  * (H / rect.height)

                // Find which text item was clicked and what sourceIdx it maps to
                let bestSourceIdx = -1
                let bestDist      = Infinity

                let charOffset = 0
                for (const item of textItems) {
                  if (!item.str) continue
                  const [a, b, c, d, tx, ty] = item.transform
                  const [cx, cy] = viewport.convertToViewportPoint(tx, ty)
                  const fontH    = Math.sqrt(a * a + b * b) * viewport.scale
                  const itemW    = Math.abs(item.width) * viewport.scale

                  // Check if click is within this item's highlight rect
                  if (mx >= cx && mx <= cx + itemW && my >= cy - fontH && my <= cy + fontH * 0.25) {
                    for (let i = charOffset; i < charOffset + item.str.length; i++) {
                      if (charSourceMap.has(i)) {
                        bestSourceIdx = charSourceMap.get(i)!
                        bestDist      = 0
                        break
                      }
                    }
                  }
                  charOffset += item.str.length
                }

                if (bestSourceIdx >= 0) onPhraseClick(bestSourceIdx)
              })
            }
          }

          // ── 4. Text layer (top layer – for copy/select) ──────────────
          if (lib.renderTextLayer) {
            const tlDiv            = document.createElement('div')
            tlDiv.className        = styles.textLayer
            tlDiv.style.width      = W + 'px'
            tlDiv.style.height     = H + 'px'
            shell.appendChild(tlDiv)

            try {
              const task = lib.renderTextLayer({
                textContentSource: textContent,
                container:         tlDiv,
                viewport,
                textDivs:          [],
              })
              await (task.promise ?? task)
            } catch { /* cancelled or unsupported — fine */ }
          }

          setProgress({ n: pn, total })
        }

        if (!cancelled) setStatus('done')
      } catch (err) {
        if (!cancelled) {
          setErrorMsg(err instanceof Error ? err.message : String(err))
          setStatus('error')
        }
      }
    }

    run()
    return () => { cancelled = true }

  // Re-render only when the URL or phrases change
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pdfUrl, authToken, JSON.stringify(phrases)])

  return (
    <div className={styles.viewer}>
      {/* Loading bar */}
      {status === 'loading' && (
        <div className={styles.loadingBar}>
          <div className={styles.spinner} />
          {progress.total > 0
            ? `Rendering page ${progress.n} / ${progress.total}…`
            : 'Loading document…'}
        </div>
      )}

      {status === 'error' && (
        <div className={styles.errorBox}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          Could not load PDF: {errorMsg}
        </div>
      )}

      {/* Pages rendered by JS into this div */}
      <div ref={wrapRef} className={styles.pages} />
    </div>
  )
}
