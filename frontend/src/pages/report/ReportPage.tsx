import { useEffect, useState, useRef, type ReactNode } from 'react'
import React from 'react'
import { useNavigate } from 'react-router-dom'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import { generatePdfReport } from '../../utils/report'
import type { EngineReport, EngineMatch, EngineSource } from '../../utils/report'
import styles from './ReportPage.module.css'
import PdfViewer, { type PhraseEntry } from './PdfViewer'

// Register the useGSAP plugin at module level
gsap.registerPlugin(useGSAP)

// ── Storage key (shared with AnalyzerPage + HistoryPage) ──────────────────────

export const REPORT_STORAGE_KEY = 'sentinel_report_data'

export interface StoredReport {
  report:      EngineReport
  filename:    string
  date:        string
  documentId:  number
  autoPrint?:  boolean   // if true, trigger window.print() after page loads
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function scoreColor(pct: number): string {
  if (pct <= 15) return '#16a34a'
  if (pct <= 40) return '#d97706'
  return '#dc2626'
}
function scoreBg(pct: number): string {
  if (pct <= 15) return '#f0fdf4'
  if (pct <= 40) return '#fffbeb'
  return '#fef2f2'
}
function scoreBorder(pct: number): string {
  if (pct <= 15) return '#bbf7d0'
  if (pct <= 40) return '#fde68a'
  return '#fecaca'
}

// ── Pure module-scope helpers ─────────────────────────────────────────────────

function handleDownload() { window.print() }

// ── Build phrase list for PDF.js highlighter ──────────────────────────────────
//
// Three highlight tiers (maps to PhraseEntry.severity):
//   identical      (red)   — verbatim phrases from exact_copied_phrases
//   highly_similar (amber) — query_text chunk for high-sim but non-verbatim matches
//   paraphrased    (purple)— query_text chunk for semantic / reranker-detected paraphrases
//
// Every match contributes at most two entries:
//   1. Each verbatim phrase → severity='identical' (red exact-phrase highlight)
//   2. The full query_text  → severity from _matchSeverity (chunk-level block highlight)
//      Only emitted when detection='paraphrase' OR there are no verbatim phrases
//      (avoids a redundant chunk highlight when verbatim phrases already cover it).

function buildPhrases(report: EngineReport): PhraseEntry[] {
  const entries: PhraseEntry[] = []
  report.sources.forEach((src, si) => {
    src.matches.forEach(m => {
      const sev         = _matchSeverity(m)
      const exactPhrases = (m.exact_copied_phrases ?? []).filter(p => p.trim().length > 8)

      // Verbatim phrases → always 'identical' (red), regardless of overall severity
      exactPhrases.forEach(ph =>
        entries.push({ phrase: ph.trim(), sourceIdx: si, severity: 'identical' })
      )

      // Chunk-level highlight for paraphrase / high-sim matches with no verbatim phrases
      const isParaphrase = m.detection === 'paraphrase'
      const impliedPara  = exactPhrases.length === 0
      if (isParaphrase || impliedPara) {
        const qt = m.query_text?.trim()
        if (qt && qt.length > 15)
          entries.push({ phrase: qt, sourceIdx: si, severity: sev })
      }
    })
  })
  return entries
}

// ── Full-document highlighter (used in print section) ────────────────────────
//
// Four-state char map — mirrors PhraseEntry.severity + overlap detection:
//   0 = no match
//   1 = identical      → red
//   2 = highly_similar → amber
//   3 = paraphrased    → purple
//
// Priority: lower number always wins (identical > similar > paraphrase).
// When a second *different* source claims a char that already has a type,
// the higher-priority type is kept.

const _SEVERITY_TYPE: Record<PhraseEntry['severity'], 1 | 2 | 3> = {
  identical:      1,
  highly_similar: 2,
  paraphrased:    3,
}

function DocumentHighlighter({ text, phrases }: { text: string; phrases: PhraseEntry[] }) {
  const lower   = text.toLowerCase()
  const len     = text.length
  const typeArr = new Uint8Array(len)           // 0=none 1=identical 2=similar 3=para
  const srcArr  = new Int32Array(len).fill(-1)  // which source last wrote each char

  // Longest phrases first so sub-phrases don't shadow broader matches
  for (const { phrase, sourceIdx, severity } of phrases.toSorted((a, b) => b.phrase.length - a.phrase.length)) {
    const newType = _SEVERITY_TYPE[severity]
    const ph = phrase.toLowerCase().trim()
    if (ph.length < 6) continue
    let pos = 0
    while (pos < len) {
      const idx = lower.indexOf(ph, pos)
      if (idx === -1) break
      for (let i = idx; i < idx + ph.length; i++) {
        const cur = typeArr[i]
        // Write if: unclaimed, OR higher priority (lower number), OR same priority different source
        if (cur === 0 || newType < cur) {
          typeArr[i] = newType
          srcArr[i]  = sourceIdx
        }
        // Same priority, different source → keep existing (first-wins within same tier)
      }
      pos = idx + ph.length
    }
  }

  const nodes: React.ReactNode[] = []
  let i = 0
  while (i < len) {
    if (typeArr[i] === 0) {
      let j = i; while (j < len && typeArr[j] === 0) j++
      nodes.push(<span key={`t${i}`}>{text.slice(i, j)}</span>)
      i = j
    } else {
      const t = typeArr[i]
      let j = i; while (j < len && typeArr[j] === t) j++
      const cls = t === 1 ? styles.inlineExact
                : t === 2 ? styles.inlineSimilar
                :            styles.inlinePara
      nodes.push(<mark key={`m${i}`} className={cls}>{text.slice(i, j)}</mark>)
      i = j
    }
  }
  return <>{nodes}</>
}

// ── Inline phrase highlighter (inside match cards) ────────────────────────────

function HighlightedText({ text, phrases, isExact }: {
  text:    string
  phrases: string[]
  isExact: boolean
}) {
  if (!phrases.length) return <>{text}</>

  const lower  = text.toLowerCase()
  const marked = new Uint8Array(text.length)

  for (const ph of phrases.toSorted((a, b) => b.length - a.length)) {
    const p = ph.toLowerCase().trim()
    if (p.length < 4) continue
    let pos = 0
    while (pos < lower.length) {
      const idx = lower.indexOf(p, pos)
      if (idx === -1) break
      marked.fill(1, idx, idx + p.length)
      pos = idx + p.length
    }
  }

  const nodes: React.ReactNode[] = []
  let i = 0
  while (i < text.length) {
    if (!marked[i]) {
      let j = i; while (j < text.length && !marked[j]) j++
      nodes.push(<span key={`t${i}`}>{text.slice(i, j)}</span>)
      i = j
    } else {
      let j = i; while (j < text.length && marked[j]) j++
      nodes.push(
        <mark key={`m${i}`} className={isExact ? styles.inlineExact : styles.inlinePara}>
          {text.slice(i, j)}
        </mark>
      )
      i = j
    }
  }
  return <>{nodes}</>
}

// ── Severity helpers ──────────────────────────────────────────────────────────
//
// Match-level severity (falls back to match_percentage for old cached reports):
//   identical      (≥ 0.95)   → red
//   highly_similar (0.85-0.95)→ amber
//   paraphrased    (< 0.85)   → purple / reranker path

function _matchSeverity(match: EngineMatch): 'identical' | 'highly_similar' | 'paraphrased' {
  if (match.severity) return match.severity
  if (match.detection === 'paraphrase') return 'paraphrased'
  const pct = match.match_percentage ?? 0
  if (pct >= 95) return 'identical'
  if (pct >= 85) return 'highly_similar'
  return 'paraphrased'
}

// Source-level severity — highest severity across all its matches.
function _srcTopSeverity(src: EngineSource): 'identical' | 'highly_similar' | 'paraphrased' {
  if (src.has_exact_copies) return 'identical'
  if (src.matches.some(m => _matchSeverity(m) === 'highly_similar')) return 'highly_similar'
  return 'paraphrased'
}

function MatchCard({ match, index }: { match: EngineMatch; index: number }) {
  const severity = _matchSeverity(match)
  const phrases  = match.exact_copied_phrases ?? []

  const dotCls    = severity === 'identical'      ? styles.dotExact
                  : severity === 'highly_similar' ? styles.dotSimilar
                  :                                 styles.dotPara
  const badgeCls  = severity === 'identical'      ? styles.badgeExact
                  : severity === 'highly_similar' ? styles.badgeSimilar
                  :                                 styles.badgePara
  const accentCls = severity === 'identical'      ? styles.accentExact
                  : severity === 'highly_similar' ? styles.accentSimilar
                  :                                 styles.accentPara
  const labelCls  = severity === 'identical'      ? styles.labelRed
                  : severity === 'highly_similar' ? styles.labelAmber
                  :                                 styles.labelPurple
  const phraseCls = severity === 'identical'      ? styles.phraseRed
                  : severity === 'highly_similar' ? styles.phraseRed   // amber phrases still red-highlight
                  :                                 styles.phrasePurple
  const label     = severity === 'identical'      ? 'Exact copy'
                  : severity === 'highly_similar' ? 'Highly similar'
                  :                                 'Paraphrase'

  return (
    <div className={styles.matchCard}>

      {/* ── Header ── */}
      <div className={styles.matchHeader}>
        <div className={styles.matchHeaderLeft}>
          <div className={`${styles.matchDot} ${dotCls}`} />
          <span className={styles.matchNum}>{index + 1}.</span>
          <span className={`${styles.matchKindBadge} ${badgeCls}`}>{label}</span>
        </div>
        <span className={styles.matchSimPill}>{match.match_percentage.toFixed(1)}% similarity</span>
      </div>

      <div className={styles.matchBody}>

        {/* ── YOUR TEXT ── */}
        <p className={styles.blockLabel}>YOUR TEXT</p>
        <div className={`${styles.docTextBlock} ${accentCls}`}>
          <HighlightedText
            text={match.query_text}
            phrases={phrases}
            isExact={severity === 'identical'}
          />
        </div>

        {/* ── MATCHED SOURCE ── */}
        {match.db_text && (
          <>
            <p className={styles.blockLabel}>MATCHED SOURCE</p>
            <div className={`${styles.sourceTextBlock} ${accentCls}`}>
              {match.db_text}
            </div>
          </>
        )}

        {/* ── EXACT PHRASES ── */}
        {phrases.length > 0 && (
          <div className={styles.phrasesBlock}>
            <p className={`${styles.blockLabel} ${labelCls}`}>
              EXACT PHRASES
            </p>
            {phrases.map((ph, i) => (
              <p key={ph || i} className={`${styles.phrase} ${phraseCls}`}>
                "{ph}"
              </p>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ReportPage() {
  "use no memo"

  const navigate = useNavigate()
  const [stored, setStored]     = useState<StoredReport | null>(null)
  const [expanded, setExpanded] = useState<number | null>(0)
  const detailsRef  = useRef<HTMLDivElement>(null)

  // ── GSAP refs ────────────────────────────────────────────────────────────────
  const containerRef = useRef<HTMLDivElement>(null)
  const arcRef       = useRef<SVGCircleElement>(null)
  const scoreNumRef  = useRef<HTMLSpanElement>(null)

  // ── Load from sessionStorage ──────────────────────────────────────────────────
  useEffect(() => {
    const raw = sessionStorage.getItem(REPORT_STORAGE_KEY)
    if (!raw) { navigate('/check'); return }
    try {
      const parsed = JSON.parse(raw) as StoredReport
      setStored(parsed)
      if (parsed.autoPrint) {
        const id = setTimeout(() => window.print(), 1800)
        return () => clearTimeout(id)
      }
    } catch { navigate('/check') }
  }, [navigate])

  // ── Entrance animations (fires when stored data becomes available) ────────────
  useGSAP(() => {
    if (!stored) return
    const sim  = stored.report.global_plagiarism_score_percent ?? 0
    const r    = 68
    const circ = 2 * Math.PI * r

    // 1. Cover card slides up + fades in
    gsap.fromTo('[data-gsap="cover"]',
      { opacity: 0, y: 24 },
      { opacity: 1, y: 0, duration: 0.6, ease: 'power3.out' }
    )

    // 2. Status badge drops in slightly after cover
    gsap.fromTo('[data-gsap="cover-badge"]',
      { opacity: 0, y: -6 },
      { opacity: 1, y: 0, duration: 0.4, ease: 'power2.out', delay: 0.18 }
    )

    // 3. Score ring draws from zero, number counts up
    if (arcRef.current && scoreNumRef.current) {
      gsap.set(arcRef.current, { attr: { 'stroke-dasharray': `0 ${circ}` } })

      const proxy = { dash: 0, count: 0 }
      gsap.to(proxy, {
        dash:  circ * (sim / 100),
        count: sim,
        duration: 1.8,
        ease: 'power4.out',
        delay: 0.14,
        onUpdate() {
          arcRef.current?.setAttribute('stroke-dasharray', `${proxy.dash} ${circ - proxy.dash}`)
          if (scoreNumRef.current) scoreNumRef.current.textContent = proxy.count.toFixed(1)
        },
      })
    }

    // 4. Stat cards stagger up
    gsap.fromTo('[data-gsap="stat-card"]',
      { opacity: 0, y: 14 },
      { opacity: 1, y: 0, duration: 0.42, stagger: 0.09, ease: 'power2.out', delay: 0.28 }
    )

    // 5. Table rows cascade in from left
    gsap.fromTo('[data-gsap="table-row"]',
      { opacity: 0, x: -10 },
      { opacity: 1, x: 0, duration: 0.3, stagger: 0.055, ease: 'power2.out', delay: 0.5 }
    )

  }, { scope: containerRef, dependencies: [stored] })

  // ── Scroll to source ──────────────────────────────────────────────────────────
  function scrollToSource(sourceIdx: number) {
    setExpanded(sourceIdx)
    setTimeout(() => {
      document.getElementById(`src-${sourceIdx}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 80)
  }

  if (!stored) return null

  const { report, filename, date, documentId } = stored
  const sim       = report.global_plagiarism_score_percent ?? 0
  const sCol      = scoreColor(sim)
  const sources   = report.sources ?? []
  const authToken = localStorage.getItem('access_token')
  const API       = (import.meta as any).env?.VITE_API_URL ?? 'http://localhost:8000/api'
  const pdfUrl    = `${API}/documents/${documentId}/file`
  const phrases   = buildPhrases(report)

  // Ring geometry — must match values used inside useGSAP
  const R    = 68
  const circ = 2 * Math.PI * R

  return (
    <div ref={containerRef} className={styles.page}>
      <main className={styles.main}>

        {/* ── Print-only header ── */}
        <div className={styles.printHeader}>
          <div className={styles.printHeaderLeft}>
            <span className={styles.printLogo}>SENTINEL</span>
            <span className={styles.printLogoSub}>Anti-Plagiarism Report</span>
          </div>
          <div className={styles.printHeaderRight}>
            <span className={styles.printHeaderFile}>{filename}</span>
            <span className={styles.printHeaderDate}>{date}</span>
          </div>
        </div>

        {/* ── Sticky top bar ── */}
        <div className={styles.topBar}>
          <div className={styles.topBarLeft}>
            <span className={styles.topBarFile}>{filename}</span>
            <span className={styles.topBarMeta}>{date}&nbsp;·&nbsp;All matches</span>
          </div>
          <div className={styles.topBarRight}>
            <button type="button" className={styles.btnDownload} onClick={handleDownload}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="7 10 12 15 17 10"/>
                <line x1="12" y1="15" x2="12" y2="3"/>
              </svg>
              Download PDF
            </button>
            <button type="button" className={styles.btnBack} onClick={() => navigate('/check')}>
              ← New check
            </button>
          </div>
        </div>

        <div className={styles.content}>

          {/* ══ COVER ════════════════════════════════════════════════════════ */}
          <section className={styles.cover} data-gsap="cover">

            {/* ── Score hero — ring left, meta + stats right ── */}
            <div className={styles.scoreHero}>

              {/* Animated SVG ring with glow */}
              <div className={styles.ringWrap}>
                <svg
                  width="168"
                  height="168"
                  viewBox="0 0 168 168"
                  className={styles.ringsvg}
                >
                  {/* Track */}
                  <circle
                    cx="84" cy="84" r={R}
                    fill="none"
                    stroke="rgba(255,255,255,0.07)"
                    strokeWidth="10"
                  />
                  {/* Animated arc with colour glow */}
                  <circle
                    ref={arcRef}
                    cx="84" cy="84" r={R}
                    fill="none"
                    stroke={sCol}
                    strokeWidth="10"
                    strokeLinecap="round"
                    strokeDasharray={`0 ${circ}`}
                    transform="rotate(-90 84 84)"
                    style={{ filter: `drop-shadow(0 0 8px ${sCol}99)` }}
                  />
                </svg>

                {/* Number overlay */}
                <div className={styles.ringCenter}>
                  <span className={styles.ringScore} style={{ color: sCol }}>
                    <span ref={scoreNumRef}>0</span>%
                  </span>
                  <span className={styles.ringLabel}>Similarity</span>
                </div>
              </div>

              {/* Right side: status badge + title + meta + stats */}
              <div className={styles.heroRight}>
                {/* Status pill */}
                <div className={styles.statusBadge} data-gsap="cover-badge">
                  <svg width="7" height="7" viewBox="0 0 7 7" aria-hidden="true">
                    <circle cx="3.5" cy="3.5" r="3.5" fill="#4ade80" />
                  </svg>
                  Analysis complete
                </div>

                <h1 className={styles.coverTitle}>{filename}</h1>
                <p className={styles.coverMeta}>
                  {date}
                  {report.analysis_config?.timing?.total_s != null && (
                    <>&nbsp;·&nbsp;Processed in {report.analysis_config.timing.total_s.toFixed(1)}s</>
                  )}
                </p>

                {/* Stat strip */}
                <div className={styles.statBar}>
                  {[
                    { val: String(report.total_reported_sources ?? sources.length), lbl: 'Sources', stat: 'sources' },
                    { val: String(report.document_stats?.total_chunks_analyzed ?? 0), lbl: 'Chunks', stat: 'chunks' },
                    { val: (report.document_stats?.total_words ?? 0).toLocaleString(), lbl: 'Words', stat: 'words' },
                  ].map((s) => (
                    <div key={s.lbl} className={styles.statCard} data-gsap="stat-card" data-stat={s.stat}>
                      <span className={styles.statCardVal}>{s.val}</span>
                      <span className={styles.statCardLbl}>{s.lbl}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <hr className={styles.divider} />

            {/* Sources summary table */}
            {sources.length > 0 && (
              <div className={styles.sourcesTable}>
                <p className={styles.sectionHeading}>Matched Sources</p>
                <div className={styles.tableHead}>
                  <span>TYPE</span>
                  <span style={{ flex: 1 }}>SOURCE</span>
                  <span>MATCHES</span>
                  <span>DOC COVERAGE</span>
                </div>
                {sources.map((src, i) => {
                  const sev = _srcTopSeverity(src)
                  const tblBadgeCls = sev === 'identical'      ? styles.badgeExact
                                    : sev === 'highly_similar' ? styles.badgeSimilar
                                    :                            styles.badgePara
                  const tblLabel    = sev === 'identical'      ? 'EXACT'
                                    : sev === 'highly_similar' ? 'SIM.'
                                    :                            'PARA.'
                  const contrib = src.score_contribution_percent
                  return (
                    <div
                      key={src.arxiv_id}
                      className={styles.tableRow}
                      data-gsap="table-row"
                      role="button"
                      tabIndex={0}
                      onClick={() => scrollToSource(i)}
                      onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && scrollToSource(i)}
                    >
                      <span className={`${styles.badge} ${tblBadgeCls}`}>{tblLabel}</span>
                      <div className={styles.srcCell}>
                        <span className={styles.srcTitle}>{i + 1}.&nbsp;&nbsp;{src.title || src.arxiv_id}</span>
                        <a
                          href={`https://arxiv.org/abs/${src.arxiv_id}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={styles.srcLink}
                          onClick={e => e.stopPropagation()}
                        >
                          arxiv.org/abs/{src.arxiv_id}
                        </a>
                      </div>
                      <span className={styles.colCenter}>{src.match_count}</span>
                      <span
                        className={styles.colCenter}
                        style={{ color: scoreColor(contrib ?? src.average_similarity_percent), fontWeight: 700 }}
                      >
                        {contrib != null ? `${contrib.toFixed(1)}%` : `~${src.average_similarity_percent.toFixed(1)}%`}
                      </span>
                    </div>
                  )
                })}
              </div>
            )}

            {sources.length === 0 && (
              <div className={styles.noSources}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#16a34a" strokeWidth="2.5" strokeLinecap="round">
                  <polyline points="20 6 9 17 4 12"/>
                </svg>
                No plagiarism detected — your document appears to be original.
              </div>
            )}
          </section>

          {/* ══ SUBMITTED DOCUMENT ══════════════════════════════════════════ */}
          <section className={styles.docSection}>
            <div className={styles.docSectionHeader}>
              <h2 className={styles.docSectionTitle}>Submitted Document</h2>
              <p className={styles.docSectionSub}>
                Exact matched phrases are highlighted
                <span className={styles.legendChip}>red</span>
                inline. Click any highlight to jump to its source details.
              </p>
              {sources.length > 0 && (
                <div className={styles.legendRow}>
                  {sources.map((src, i) => (
                    <button type="button" key={src.arxiv_id} className={styles.legendChipBtn} onClick={() => scrollToSource(i)}>
                      <span className={styles.legendDot} />
                      {i + 1}. {src.title || src.arxiv_id}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Screen: PDF canvas viewer */}
            <div className={styles.screenOnly}>
              <PdfViewer
                pdfUrl={pdfUrl}
                authToken={authToken}
                phrases={phrases}
                onPhraseClick={scrollToSource}
              />
            </div>

            {/* Print: inline highlighted text (canvases don't print) */}
            {(report.display_text || report.full_text) && (
              <div className={styles.printOnly}>
                <div className={styles.printDocLegend}>
                  <span className={styles.printLegendExact}>■ Exact copy</span>
                  <span className={styles.printLegendSimilar}>■ Highly similar</span>
                  <span className={styles.printLegendPara}>■ Paraphrase</span>
                </div>
                <div className={styles.printDocText}>
                  <DocumentHighlighter
                    text={report.display_text ?? report.full_text ?? ''}
                    phrases={phrases}
                  />
                </div>
              </div>
            )}
          </section>

          {/* ══ SOURCE DETAIL SECTIONS ══════════════════════════════════════ */}
          {sources.length > 0 && (
            <div ref={detailsRef}>
              <p className={styles.sectionHeading} style={{ marginBottom: 12 }}>SIMILARITY DETAILS</p>

              {sources.map((src, si) => {
                const sev     = _srcTopSeverity(src)
                const numCls  = sev === 'identical'      ? styles.numExact
                              : sev === 'highly_similar' ? styles.numSimilar
                              :                            styles.numPara
                const badgeCls = sev === 'identical'      ? styles.badgeExact
                               : sev === 'highly_similar' ? styles.badgeSimilar
                               :                            styles.badgePara
                const sevLabel = sev === 'identical'      ? 'EXACT COPY'
                               : sev === 'highly_similar' ? 'HIGHLY SIMILAR'
                               :                            'PARAPHRASE'
                const contrib  = src.score_contribution_percent
                const contribCol = contrib != null
                  ? scoreColor(contrib)
                  : scoreColor(src.average_similarity_percent)

                return (
                  <section key={src.arxiv_id} id={`src-${si}`} className={styles.sourceSection}>
                    <div
                      className={styles.sourceHeader}
                      role="button"
                      tabIndex={0}
                      onClick={() => setExpanded(expanded === si ? null : si)}
                      onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && setExpanded(expanded === si ? null : si)}
                      aria-expanded={expanded === si}
                    >
                      <div className={styles.srcHeaderLeft}>
                        <div className={`${styles.srcNum} ${numCls}`}>{si + 1}</div>
                        <span className={`${styles.badge} ${badgeCls}`}>{sevLabel}</span>
                        <div className={styles.srcHeaderInfo}>
                          <span className={styles.srcHeaderTitle}>{src.title || src.arxiv_id}</span>
                          <a
                            href={`https://arxiv.org/abs/${src.arxiv_id}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className={styles.srcLink}
                            onClick={e => e.stopPropagation()}
                          >
                            arxiv.org/abs/{src.arxiv_id}
                          </a>
                        </div>
                      </div>
                      <div className={styles.srcHeaderRight}>
                        {/* Primary: how much of YOUR document this source covers */}
                        <div className={styles.srcMetaStack}>
                          <span className={styles.srcSimBig} style={{ color: contribCol }}>
                            {contrib != null
                              ? `${contrib.toFixed(1)}%`
                              : `${src.average_similarity_percent.toFixed(1)}%`}
                          </span>
                          <span className={styles.srcContribLbl}>
                            {contrib != null ? 'of document' : 'avg sim'}
                          </span>
                          {contrib != null && (
                            <span className={styles.srcSimSub}>
                              avg {src.average_similarity_percent.toFixed(1)}% match
                            </span>
                          )}
                        </div>
                        <span className={styles.srcMatchCount}>{src.match_count} matches</span>
                        <span className={styles.chevron}>{expanded === si ? '▲' : '▼'}</span>
                      </div>
                    </div>

                    {expanded === si && (
                      <div className={styles.matchList}>
                        {src.matches.map((m, mi) => <MatchCard key={mi} match={m} index={mi} />)}
                      </div>
                    )}
                  </section>
                )
              })}
            </div>
          )}
        </div>

        <footer className={styles.footer}>
          <span>ID: sentinel:{documentId}</span>
          <span>{date}</span>
        </footer>
      </main>
    </div>
  )
}
