import { useEffect, useState, useRef, type ReactNode } from 'react'
import React from 'react'
import { useNavigate } from 'react-router-dom'
import { generatePdfReport } from '../../utils/report'
import type { EngineReport, EngineMatch } from '../../utils/report'
import styles from './ReportPage.module.css'
import PdfViewer, { type PhraseEntry } from './PdfViewer'
import Navbar from '../../components/shared/navbar/Navbar'

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

// ── Build phrase list for PDF.js highlighter ──────────────────────────────────

function buildPhrases(report: EngineReport): PhraseEntry[] {
  const entries: PhraseEntry[] = []
  report.sources.forEach((src, si) => {
    src.matches.forEach(m => {
      const isExact = m.detection !== 'paraphrase'
      ;(m.exact_copied_phrases ?? []).forEach(ph => {
        if (ph.trim().length > 8) entries.push({ phrase: ph.trim(), sourceIdx: si, isExact })
      })
    })
  })
  return entries
}

// ── Full-document highlighter (used in the print document section) ────────────
// Renders the entire document text with ALL matched phrases highlighted inline,
// using red for exact copies and purple for paraphrases.

function DocumentHighlighter({ text, phrases }: { text: string; phrases: PhraseEntry[] }) {
  const lower  = text.toLowerCase()
  const len    = text.length
  const srcArr = new Int32Array(len).fill(-1)  // charIdx → sourceIdx
  const exArr  = new Uint8Array(len)           // charIdx → isExact

  // Longest phrases first so sub-phrases don't override longer matches
  for (const { phrase, sourceIdx, isExact } of [...phrases].sort((a, b) => b.phrase.length - a.phrase.length)) {
    const ph = phrase.toLowerCase().trim()
    if (ph.length < 6) continue
    let pos = 0
    while (pos < len) {
      const idx = lower.indexOf(ph, pos)
      if (idx === -1) break
      for (let i = idx; i < idx + ph.length; i++) {
        if (srcArr[i] === -1) { srcArr[i] = sourceIdx; exArr[i] = isExact ? 1 : 0 }
      }
      pos = idx + ph.length
    }
  }

  const nodes: React.ReactNode[] = []
  let i = 0, key = 0
  while (i < len) {
    if (srcArr[i] === -1) {
      let j = i; while (j < len && srcArr[j] === -1) j++
      nodes.push(<span key={key++}>{text.slice(i, j)}</span>)
      i = j
    } else {
      const ex = exArr[i]
      let j = i; while (j < len && srcArr[j] !== -1 && exArr[j] === ex) j++
      nodes.push(
        <mark key={key++} className={ex ? styles.inlineExact : styles.inlinePara}>
          {text.slice(i, j)}
        </mark>
      )
      i = j
    }
  }
  return <>{nodes}</>
}

// ── Inline phrase highlighter (used inside match cards) ───────────────────────

function HighlightedText({ text, phrases, isExact }: {
  text:    string
  phrases: string[]
  isExact: boolean
}) {
  if (!phrases.length) return <>{text}</>

  const lower  = text.toLowerCase()
  const marked = new Uint8Array(text.length)  // 1 = highlighted

  for (const ph of [...phrases].sort((a, b) => b.length - a.length)) {
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
  let i = 0, key = 0
  while (i < text.length) {
    if (!marked[i]) {
      let j = i; while (j < text.length && !marked[j]) j++
      nodes.push(<span key={key++}>{text.slice(i, j)}</span>)
      i = j
    } else {
      let j = i; while (j < text.length && marked[j]) j++
      nodes.push(
        <mark key={key++} className={isExact ? styles.inlineExact : styles.inlinePara}>
          {text.slice(i, j)}
        </mark>
      )
      i = j
    }
  }
  return <>{nodes}</>
}

// ── MatchCard ─────────────────────────────────────────────────────────────────

function MatchCard({ match, index }: { match: EngineMatch; index: number }) {
  const isExact = match.detection !== 'paraphrase'
  const phrases = match.exact_copied_phrases ?? []
  const accentCls = isExact ? styles.accentExact : styles.accentPara

  return (
    <div className={styles.matchCard}>

      {/* ── Header ── */}
      <div className={styles.matchHeader}>
        <div className={styles.matchHeaderLeft}>
          <div className={`${styles.matchDot} ${isExact ? styles.dotExact : styles.dotPara}`} />
          <span className={styles.matchNum}>{index + 1}.</span>
          <span className={`${styles.matchKindBadge} ${isExact ? styles.badgeExact : styles.badgePara}`}>
            {isExact ? 'Exact copy' : 'Paraphrase'}
          </span>
        </div>
        <span className={styles.matchSimPill}>{match.match_percentage.toFixed(1)}% similarity</span>
      </div>

      <div className={styles.matchBody}>

        {/* ── YOUR TEXT — document style with inline phrase highlights ── */}
        <p className={styles.blockLabel}>YOUR TEXT</p>
        <div className={`${styles.docTextBlock} ${accentCls}`}>
          <HighlightedText
            text={match.query_text}
            phrases={phrases}
            isExact={isExact}
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

        {/* ── EXACT PHRASES — italicised below ── */}
        {phrases.length > 0 && (
          <div className={styles.phrasesBlock}>
            <p className={`${styles.blockLabel} ${isExact ? styles.labelRed : styles.labelPurple}`}>
              EXACT PHRASES
            </p>
            {phrases.map((ph, i) => (
              <p key={i} className={`${styles.phrase} ${isExact ? styles.phraseRed : styles.phrasePurple}`}>
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
  const navigate = useNavigate()
  const [stored, setStored]           = useState<StoredReport | null>(null)
  const [downloading, setDownloading] = useState(false)
  const [expanded, setExpanded]       = useState<number | null>(0)
  const detailsRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const raw = sessionStorage.getItem(REPORT_STORAGE_KEY)
    if (!raw) { navigate('/check'); return }
    try {
      const parsed = JSON.parse(raw) as StoredReport
      setStored(parsed)
      if (parsed.autoPrint) {
        // Wait for the page to fully render before printing
        setTimeout(() => window.print(), 1800)
      }
    } catch { navigate('/check') }
  }, [navigate])

  function handleDownload() {
    window.print()
  }

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

  return (
    <div className={styles.page}>
      <Navbar />

      <main className={styles.main}>

        {/* ── Print-only header (hidden on screen) ── */}
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

        {/* ── Top action bar (hidden in print) ── */}
        <div className={styles.topBar}>
          <div className={styles.topBarLeft}>
            <span className={styles.topBarFile}>{filename}</span>
            <span className={styles.topBarMeta}>{date}&nbsp;·&nbsp;All matches</span>
          </div>
          <div className={styles.topBarRight}>
            <button className={styles.btnDownload} onClick={handleDownload} disabled={downloading}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              {downloading ? 'Generating…' : 'Download PDF'}
            </button>
            <button className={styles.btnBack} onClick={() => navigate('/check')}>
              ← New check
            </button>
          </div>
        </div>

      <div className={styles.content}>

        {/* ══ COVER ════════════════════════════════════════════════════════ */}
        <section className={styles.cover}>
          <h1 className={styles.coverTitle}>{filename}</h1>
          <p className={styles.coverMeta}>{date}&nbsp;·&nbsp;All matches</p>

          {/* ── Score hero ── */}
          <div className={styles.scoreHero}>
            {/* SVG donut ring */}
            <div className={styles.ringWrap}>
              <svg width="140" height="140" viewBox="0 0 140 140" className={styles.ringsvg}>
                <circle cx="70" cy="70" r="56" fill="none" stroke="#e5e7eb" strokeWidth="10"/>
                <circle
                  cx="70" cy="70" r="56"
                  fill="none"
                  stroke={sCol}
                  strokeWidth="10"
                  strokeLinecap="round"
                  strokeDasharray={`${2 * Math.PI * 56}`}
                  strokeDashoffset={`${2 * Math.PI * 56 * (1 - sim / 100)}`}
                  transform="rotate(-90 70 70)"
                  style={{ transition: 'stroke-dashoffset 1.2s cubic-bezier(.4,0,.2,1)' }}
                />
                <text x="70" y="65" textAnchor="middle" fill={sCol}
                  fontSize="22" fontWeight="800" fontFamily="-apple-system,'Segoe UI',sans-serif">
                  {sim.toFixed(1)}%
                </text>
                <text x="70" y="83" textAnchor="middle" fill={sCol}
                  fontSize="8.5" fontWeight="700" letterSpacing="0.8"
                  fontFamily="-apple-system,'Segoe UI',sans-serif">
                  SIMILARITY
                </text>
              </svg>
            </div>

            {/* Stat bar */}
            <div className={styles.statBar}>
              {[
                { val: String(report.total_reported_sources ?? sources.length), lbl: 'Sources matched', icon: '⊙' },
                { val: String(report.document_stats?.total_chunks_analyzed ?? 0), lbl: 'Chunks analyzed', icon: '≡' },
                { val: (report.document_stats?.total_words ?? 0).toLocaleString(), lbl: 'Words', icon: '∷' },
              ].map((s, i) => (
                <div key={s.lbl} className={styles.statCard}>
                  <span className={styles.statCardVal}>{s.val}</span>
                  <span className={styles.statCardLbl}>{s.lbl}</span>
                </div>
              ))}
            </div>
          </div>

          <hr className={styles.divider} />

          {/* Sources summary table */}
          {sources.length > 0 && (
            <div className={styles.sourcesTable}>
              <p className={styles.sectionHeading}>MATCHED SOURCES</p>
              <div className={styles.tableHead}>
                <span>TYPE</span>
                <span style={{ flex: 1 }}>SOURCE</span>
                <span>MATCHES</span>
                <span>SIM %</span>
              </div>
              {sources.map((src, i) => (
                <div
                  key={src.arxiv_id}
                  className={styles.tableRow}
                  onClick={() => scrollToSource(i)}
                >
                  <span className={`${styles.badge} ${src.has_exact_copies ? styles.badgeExact : styles.badgePara}`}>
                    {src.has_exact_copies ? 'EXACT' : 'PARA.'}
                  </span>
                  <div className={styles.srcCell}>
                    <span className={styles.srcTitle}>{i + 1}.&nbsp;&nbsp;{src.title || src.arxiv_id}</span>
                    <a href={`https://arxiv.org/abs/${src.arxiv_id}`} target="_blank"
                      rel="noopener noreferrer" className={styles.srcLink}
                      onClick={e => e.stopPropagation()}>
                      arxiv.org/abs/{src.arxiv_id}
                    </a>
                  </div>
                  <span className={styles.colCenter}>{src.match_count}</span>
                  <span className={styles.colCenter}
                    style={{ color: scoreColor(src.average_similarity_percent), fontWeight: 700 }}>
                    {src.average_similarity_percent.toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>
          )}

          {sources.length === 0 && (
            <div className={styles.noSources}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#16a34a" strokeWidth="2.5" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
              No plagiarism detected — your document appears to be original.
            </div>
          )}
        </section>

        {/* ══ SUBMITTED DOCUMENT — rendered as actual PDF ═══════════════ */}
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
                  <button key={src.arxiv_id} className={styles.legendChipBtn} onClick={() => scrollToSource(i)}>
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

        {/* ══ SOURCE DETAIL SECTIONS ════════════════════════════════════ */}
        {sources.length > 0 && (
          <div ref={detailsRef}>
            <p className={styles.sectionHeading} style={{ marginBottom: 12 }}>SIMILARITY DETAILS</p>

            {sources.map((src, si) => (
              <section key={src.arxiv_id} id={`src-${si}`} className={styles.sourceSection}>
                <div
                  className={styles.sourceHeader}
                  onClick={() => setExpanded(expanded === si ? null : si)}
                >
                  <div className={styles.srcHeaderLeft}>
                    <div className={`${styles.srcNum} ${src.has_exact_copies ? styles.numExact : styles.numPara}`}>
                      {si + 1}
                    </div>
                    <span className={`${styles.badge} ${src.has_exact_copies ? styles.badgeExact : styles.badgePara}`}>
                      {src.has_exact_copies ? 'EXACT COPY' : 'PARAPHRASE'}
                    </span>
                    <div className={styles.srcHeaderInfo}>
                      <span className={styles.srcHeaderTitle}>{src.title || src.arxiv_id}</span>
                      <a href={`https://arxiv.org/abs/${src.arxiv_id}`} target="_blank"
                        rel="noopener noreferrer" className={styles.srcLink}
                        onClick={e => e.stopPropagation()}>
                        arxiv.org/abs/{src.arxiv_id}
                      </a>
                    </div>
                  </div>
                  <div className={styles.srcHeaderRight}>
                    <span className={styles.srcSimBig} style={{ color: scoreColor(src.average_similarity_percent) }}>
                      {src.average_similarity_percent.toFixed(1)}%
                    </span>
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
            ))}
          </div>
        )}
      </div>

      <footer className={styles.footer}>
        <span>ID: sentinel:{Date.now()}</span>
        <span>{date}</span>
      </footer>
      </main>
    </div>
  )
}
