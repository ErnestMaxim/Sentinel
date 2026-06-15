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
  /** Severity determines highlight colour: identical=red, highly_similar=amber, paraphrased=purple */
  severity:  'identical' | 'highly_similar' | 'paraphrased'
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
// Highlight colours — three severity tiers
const IDENTICAL_COLOR = 'rgba(220, 38,  38,  0.30)'  // red    – identical (≥ 95%)
const SIMILAR_COLOR   = 'rgba(217, 119,  6,  0.28)'  // amber  – highly similar (85–95%)
const PARA_COLOR      = 'rgba(124, 58,  237, 0.22)'  // purple – paraphrased (< 85%)

/**
 * Unicode Greek → ASCII token table.
 * Must match the backend's normalize_text_for_fingerprint (normalizer.py).
 * The backend converts α→ALPHA→alpha; we do the same so PDF.js-extracted
 * Unicode symbols produce the same tokens as the already-normalised query_text.
 */
const GREEK_MAP: [string, string][] = [
  ['α','alpha'],['β','beta'],['γ','gamma'],['δ','delta'],['ε','epsilon'],
  ['ζ','zeta'],['η','eta'],['θ','theta'],['ι','iota'],['κ','kappa'],
  ['λ','lambda'],['μ','mu'],['ν','nu'],['ξ','xi'],['π','pi'],['ρ','rho'],
  ['σ','sigma'],['τ','tau'],['υ','upsilon'],['φ','phi'],['χ','chi'],
  ['ψ','psi'],['ω','omega'],
  ['Γ','gamma'],['Δ','delta'],['Θ','theta'],['Λ','lambda'],['Ξ','xi'],
  ['Π','pi'],['Σ','sigma'],['Υ','upsilon'],['Φ','phi'],['Ψ','psi'],['Ω','omega'],
]

/**
 * Normalise text for paraphrase matching.
 *
 * The backend stores query_text after normalize_text_for_fingerprint which:
 *   – converts Unicode/LaTeX Greek to ASCII tokens (α→alpha, \alpha→alpha)
 *   – strips remaining LaTeX commands and delimiters
 *   – lowercases and collapses whitespace
 *
 * PDF.js extracts visual text containing Unicode math symbols and plain ASCII.
 * Applying this function to BOTH sides makes them comparable:
 *   PDF.js "α"  → "alpha"   ≡  query_text "alpha"  ✓
 *   PDF.js "R-linear" → "r linear"  ≡  query_text "r linear"  ✓
 */
function normForMatch(s: string): string {
  // 1. Unicode Greek → ASCII tokens (matches backend normalizer step 2)
  let t = s
  for (const [ch, tok] of GREEK_MAP) t = t.replaceAll(ch, ` ${tok} `)

  return t
    // 2. Inline LaTeX $...$ — strip dollar signs, keep content
    .replace(/\$([^$\n]*)\$/g, (_, inner) =>
      inner.replace(/\\[a-zA-Z]+\*?/g, ' ').replace(/[{}_^]/g, ' '))
    // 3. \cmd{inner} → inner
    .replace(/\\[a-zA-Z]+\*?\s*\{([^}]*)\}/g, ' $1 ')
    // 4. Standalone LaTeX commands → space
    .replace(/\\[a-zA-Z]+\*?/g, ' ')
    // 5. Strip ALL non-alphanumeric (hyphens, parens, commas, brackets, etc.)
    //    Both sides are reduced to bare word tokens so item-boundary punctuation
    //    differences can't break the match.
    .replace(/[^a-zA-Z0-9\s]+/g, ' ')
    // 6. Collapse whitespace, lowercase
    .replace(/\s+/g, ' ').toLowerCase().trim()
}

/**
 * Draws highlights on `overlayCanvas` for every phrase found in the page's
 * text content.
 *
 * Key design decisions
 * ────────────────────
 * 1. Each PDF text item is drawn AT MOST ONCE regardless of how many phrase
 *    matches cover it.  This prevents opacity accumulation (the "darker red"
 *    issue where the same sentence gets multiple overlapping rectangles).
 *
 * 2. severity='identical' phrases are searched verbatim in the lower-cased raw text.
 *
 * 3. severity='highly_similar' and 'paraphrased' phrases carry marker-pdf LaTeX text.
 *    They are searched in a parallel normalised string built from the same text items,
 *    using normForMatch() on both sides so the comparison is apples-to-apples.
 *
 * 4. Priority:  exact (red) always wins over paraphrase (purple) for any item
 *    that is claimed by both.
 */
function drawHighlights(
  overlayCanvas: HTMLCanvasElement,
  viewport:      any,
  textItems:     TextItem[],
  phrases:       PhraseEntry[],
): Map<number, number> /* charOffset → sourceIdx */ {

  const ctx = overlayCanvas.getContext('2d')!
  ctx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height)

  // ── Build text strings ─────────────────────────────────────────────────────
  // fullText  : raw concatenation for exact-phrase search
  // normFull  : normalised concatenation for paraphrase search
  // Both track per-item start/end so we can map matches → items.

  interface ItemRange {
    start:     number   // position in fullText
    end:       number
    normStart: number   // position in normFull
    normEnd:   number
    item:      TextItem
  }

  let fullText = ''
  let normFull = ''
  const allRanges:  ItemRange[]             = []
  const rangeByItem = new Map<TextItem, ItemRange>()

  for (const item of textItems) {
    if (!item.str) continue
    const ns = normForMatch(item.str)
    const r: ItemRange = {
      start:     fullText.length,
      end:       fullText.length + item.str.length,
      normStart: normFull.length,
      normEnd:   normFull.length + ns.length,
      item,
    }
    allRanges.push(r)
    rangeByItem.set(item, r)
    fullText += item.str
    normFull += ns + ' '  // space separator so word boundaries survive normalisation
  }
  if (!fullText) return new Map()

  const lower = fullText.toLowerCase()

  // ── Claim items ───────────────────────────────────────────────────────────
  // For each phrase match we "claim" the items it covers.
  // Priority: identical (1) > highly_similar (2) > paraphrased (3)

  const itemClaim = new Map<TextItem, { type: 1 | 2 | 3; sourceIdx: number }>()

  // Priority: identical (1) > highly_similar (2) > paraphrased (3)
  // A lower number always wins when two phrases contest the same item.
  const SEVERITY_TYPE = {
    identical:      1 as const,
    highly_similar: 2 as const,
    paraphrased:    3 as const,
  }

  function claimItemsInRange(
    rangeStart: number, rangeEnd: number,
    sourceIdx: number, type: 1 | 2 | 3,
    useNorm: boolean,
  ) {
    for (const r of allRanges) {
      const rS = useNorm ? r.normStart : r.start
      const rE = useNorm ? r.normEnd   : r.end
      if (rE <= rangeStart || rS >= rangeEnd) continue
      const existing = itemClaim.get(r.item)
      // Higher-priority type (lower number) always wins
      if (!existing || type < existing.type) {
        itemClaim.set(r.item, { type, sourceIdx })
      }
    }
  }

  for (const { phrase, sourceIdx, severity } of phrases) {
    const type = SEVERITY_TYPE[severity]

    if (severity === 'identical') {
      // ── Identical: search verbatim phrases in original (lower-cased) text ─
      const ph = phrase.toLowerCase().trim()
      if (ph.length < 6) continue
      let pos = 0
      while (pos < lower.length) {
        const idx = lower.indexOf(ph, pos)
        if (idx === -1) break
        claimItemsInRange(idx, idx + ph.length, sourceIdx, type, false)
        pos = idx + ph.length
      }
    } else {
      // ── Highly similar / Paraphrase: 5-word n-gram regex with \s+ gaps ───
      // A direct indexOf on a 100-word chunk is too brittle — one item-boundary
      // space difference anywhere in the chunk breaks the whole match.
      // Instead we slide a 5-word window (step 3) across the normalised phrase
      // and look for each n-gram with flexible whitespace between tokens.
      const normPhrase = normForMatch(phrase)
      const words = normPhrase.split(' ').filter(w => w.length > 0)
      if (words.length < 5) continue

      const NGRAM = 5
      const STEP  = 3

      for (let wi = 0; wi <= words.length - NGRAM; wi += STEP) {
        const gram = words.slice(wi, wi + NGRAM)
        // Skip trivial n-grams made mostly of short stop words
        if (gram.filter(w => w.length > 3).length < 3) continue

        // Build regex: each word separated by one-or-more whitespace chars
        const re = new RegExp(gram.join('\\s+'), 'g')
        let m: RegExpExecArray | null
        while ((m = re.exec(normFull)) !== null) {
          claimItemsInRange(m.index, m.index + m[0].length, sourceIdx, type, true)
        }
      }
    }
  }

  if (itemClaim.size === 0) return new Map()

  // ── Draw each claimed item exactly once ────────────────────────────────────
  const charSourceMap = new Map<number, number>()

  for (const [item, { type, sourceIdx }] of itemClaim) {
    // Draw the highlight rectangle
    ctx.fillStyle = type === 1 ? IDENTICAL_COLOR
                  : type === 2 ? SIMILAR_COLOR
                  :               PARA_COLOR
    const [a, b, , , tx, ty] = item.transform
    const [cx, cy] = viewport.convertToViewportPoint(tx, ty)
    const itemW    = Math.abs(item.width) * viewport.scale
    const fontH    = Math.sqrt(a * a + b * b) * viewport.scale
    if (itemW >= 1 && fontH >= 1) {
      ctx.fillRect(cx, cy - fontH, itemW, fontH * 1.25)
    }

    // Populate click-detection map
    const r = rangeByItem.get(item)
    if (r) {
      for (let c = r.start; c < r.end; c++) {
        if (!charSourceMap.has(c)) charSourceMap.set(c, sourceIdx)
      }
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
