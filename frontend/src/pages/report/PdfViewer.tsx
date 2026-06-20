import { useEffect, useRef, useState } from 'react'
import styles from './PdfViewer.module.css'

// ── Public types ───────────────────────────────────────────────────────────────
export interface PhraseEntry {
  phrase:    string
  sourceIdx: number
  severity:  'identical' | 'highly_similar' | 'paraphrased'
}

interface Props {
  pdfUrl:        string
  authToken:     string | null
  phrases:       PhraseEntry[]
  onPhraseClick: (sourceIdx: number) => void
}

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

const IDENTICAL_COLOR = 'rgba(220, 38,  38,  0.30)'  // red    – identical (≥ 95%)
const SIMILAR_COLOR   = 'rgba(217, 119,  6,  0.28)'  // amber  – highly similar (85–95%)
const PARA_COLOR      = 'rgba(124, 58,  237, 0.22)'  // purple – paraphrased (< 85%)

const GREEK_MAP: [string, string][] = [
  ['α','alpha'],['β','beta'],['γ','gamma'],['δ','delta'],['ε','epsilon'],
  ['ζ','zeta'],['η','eta'],['θ','theta'],['ι','iota'],['κ','kappa'],
  ['λ','lambda'],['μ','mu'],['ν','nu'],['ξ','xi'],['π','pi'],['ρ','rho'],
  ['σ','sigma'],['τ','tau'],['υ','upsilon'],['φ','phi'],['χ','chi'],
  ['ψ','psi'],['ω','omega'],
  ['Γ','gamma'],['Δ','delta'],['Θ','theta'],['Λ','lambda'],['Ξ','xi'],
  ['Π','pi'],['Σ','sigma'],['Υ','upsilon'],['Φ','phi'],['Ψ','psi'],['Ω','omega'],
]

function normForMatch(s: string): string {
  // Unicode Greek → ASCII tokens (matches backend normalizer step 2)
  let t = s
  for (const [ch, tok] of GREEK_MAP) t = t.replaceAll(ch, ` ${tok} `)

  return t
    // Inline LaTeX $...$ — strip dollar signs, keep content
    .replace(/\$([^$\n]*)\$/g, (_, inner) =>
      inner.replace(/\\[a-zA-Z]+\*?/g, ' ').replace(/[{}_^]/g, ' '))
    // \cmd{inner} → inner
    .replace(/\\[a-zA-Z]+\*?\s*\{([^}]*)\}/g, ' $1 ')
    // Standalone LaTeX commands → space
    .replace(/\\[a-zA-Z]+\*?/g, ' ')
    // Strip ALL non-alphanumeric (hyphens, parens, commas, brackets, etc.)
    .replace(/[^a-zA-Z0-9\s]+/g, ' ')
    .replace(/\s+/g, ' ').toLowerCase().trim()
}

function drawHighlights(
  overlayCanvas: HTMLCanvasElement,
  viewport:      any,
  textItems:     TextItem[],
  phrases:       PhraseEntry[],
): Map<number, number>{

  const ctx = overlayCanvas.getContext('2d')!
  ctx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height)
  interface ItemRange {
    start:     number
    end:       number
    normStart: number
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
    normFull += ns + ' '
  }
  if (!fullText) return new Map()

  const lower = fullText.toLowerCase()
  // ── Claim items ───────────────────────────────────────────────────────────
  const itemClaim = new Map<TextItem, { type: 1 | 2 | 3; sourceIdx: number }>()

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
      const normPhrase = normForMatch(phrase)
      const words = normPhrase.split(' ').filter(w => w.length > 0)
      if (words.length < 5) continue

      const NGRAM = 5
      const STEP  = 3

      for (let wi = 0; wi <= words.length - NGRAM; wi += STEP) {
        const gram = words.slice(wi, wi + NGRAM)
        if (gram.filter(w => w.length > 3).length < 3) continue

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
        const lib = await loadPdfJs()
        if (cancelled) return

        const res = await fetch(pdfUrl, {
          headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
        })
        if (!res.ok) throw new Error(`Server returned ${res.status}`)
        const buf = await res.arrayBuffer()
        if (cancelled) return

        const pdfDoc = await lib.getDocument({ data: buf }).promise
        if (cancelled) return

        const total = pdfDoc.numPages
        setProgress({ n: 0, total })

        const SCALE = 1.5

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

          // ── PDF canvas (bottom layer) ─────────────────────────────
          const pdfCanvas    = document.createElement('canvas')
          pdfCanvas.width    = W
          pdfCanvas.height   = H
          pdfCanvas.className = styles.pdfCanvas
          shell.appendChild(pdfCanvas)

          const pdfCtx = pdfCanvas.getContext('2d')!
          await page.render({ canvasContext: pdfCtx, viewport }).promise
          if (cancelled) return

          // ── Get text content ──────────────────────────────────────
          const textContent = await page.getTextContent()
          if (cancelled) return
          const textItems = (textContent.items ?? []) as TextItem[]

          // ── Highlight overlay canvas (middle layer) ───────────────
          if (phrases.length > 0 && textItems.length > 0) {
            const hlCanvas    = document.createElement('canvas')
            hlCanvas.width    = W
            hlCanvas.height   = H
            hlCanvas.className = styles.hlCanvas
            shell.appendChild(hlCanvas)

            const charSourceMap = drawHighlights(hlCanvas, viewport, textItems, phrases)

            if (charSourceMap.size > 0) {
              hlCanvas.addEventListener('click', (e) => {
                const rect = hlCanvas.getBoundingClientRect()
                const mx   = (e.clientX - rect.left) * (W / rect.width)
                const my   = (e.clientY - rect.top)  * (H / rect.height)

                let bestSourceIdx = -1

                let charOffset = 0
                for (const item of textItems) {
                  if (!item.str) continue
                  const [a, b, tx, ty] = item.transform
                  const [cx, cy] = viewport.convertToViewportPoint(tx, ty)
                  const fontH    = Math.sqrt(a * a + b * b) * viewport.scale
                  const itemW    = Math.abs(item.width) * viewport.scale

                  if (mx >= cx && mx <= cx + itemW && my >= cy - fontH && my <= cy + fontH * 0.25) {
                    for (let i = charOffset; i < charOffset + item.str.length; i++) {
                      if (charSourceMap.has(i)) {
                        bestSourceIdx = charSourceMap.get(i)!
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

          // ── Text layer (top layer – for copy/select) ──────────────
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
