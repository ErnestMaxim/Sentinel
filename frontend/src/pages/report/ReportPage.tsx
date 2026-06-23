import { useEffect, useState, useRef} from 'react'
import React from 'react'
import { useNavigate } from 'react-router-dom'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import type { EngineReport, EngineMatch, EngineSource } from '../../utils/report'
import styles from './ReportPage.module.css'
import PdfViewer, { type PhraseEntry } from './PdfViewer'

gsap.registerPlugin(useGSAP)

export const REPORT_STORAGE_KEY = 'sentinel_report_data'

export interface StoredReport {
  report:      EngineReport
  filename:    string
  date:        string
  documentId:  number
  autoPrint?:  boolean
}

function scoreColor(pct: number): string {
  if (pct <= 15) return '#16a34a'
  if (pct <= 40) return '#d97706'
  return '#dc2626'
}

function handleDownload() { window.print() }

function buildPhrases(report: EngineReport): PhraseEntry[] {
  const entries: PhraseEntry[] = []
  report.sources.forEach((src, si) => {
    src.matches.forEach(m => {
      const sev          = _matchSeverity(m)
      const exactPhrases = (m.exact_copied_phrases ?? []).filter(p => p.trim().length > 8)

      exactPhrases.forEach(ph =>
        entries.push({ phrase: ph.trim(), sourceIdx: si, severity: 'identical' })
      )

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

const _SEVERITY_TYPE: Record<PhraseEntry['severity'], 1 | 2 | 3> = {
  identical:      1,
  highly_similar: 2,
  paraphrased:    3,
}

function DocumentHighlighter({ text, phrases }: { text: string; phrases: PhraseEntry[] }) {
  const lower   = text.toLowerCase()
  const len     = text.length
  const typeArr = new Uint8Array(len)
  const srcArr  = new Int32Array(len).fill(-1)

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
        if (cur === 0 || newType < cur) {
          typeArr[i] = newType
          srcArr[i]  = sourceIdx
        }
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

function HighlightedText({ text, phrases, isExact }: {
  text:    string
  phrases: string[]
  isExact: boolean
}) {
  if (!phrases.length) return <>{text}</>

  const lower  = text.toLowerCase()
  const marked = new Uint8Array(text.length)

  for (const ph of phrases.toSorted((a: string, b: string) => b.length - a.length)) {
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

function _matchSeverity(match: EngineMatch): 'identical' | 'highly_similar' | 'paraphrased' {
  if (match.severity) return match.severity
  if (match.detection === 'paraphrase') return 'paraphrased'
  const pct = match.match_percentage ?? 0
  if (pct >= 95) return 'identical'
  if (pct >= 85) return 'highly_similar'
  return 'paraphrased'
}

function _srcTopSeverity(src: EngineSource): 'identical' | 'highly_similar' | 'paraphrased' {
  if (src.has_exact_copies) return 'identical'
  if (src.matches.some(m => _matchSeverity(m) === 'highly_similar')) return 'highly_similar'
  return 'paraphrased'
}

function MatchCard({ match, index }: { match: EngineMatch; index: number }) {
  const severity = _matchSeverity(match)
  const phrases  = match.exact_copied_phrases ?? []

  const kindBadgeCls = severity === 'identical'      ? styles.kindBadgeExact
                     : severity === 'highly_similar' ? styles.kindBadgeSimilar
                     :                                 styles.kindBadgePara

  const phraseCls = severity === 'identical'      ? styles.phraseRed
                  : severity === 'highly_similar' ? styles.phraseRed
                  :                                 styles.phrasePurple

  const labelCls = severity === 'identical'      ? styles.labelRed
                 : severity === 'highly_similar' ? styles.labelAmber
                 :                                 styles.labelPurple

  const label = severity === 'identical'      ? 'Exact copy'
              : severity === 'highly_similar' ? 'Highly similar'
              :                                 'Paraphrase'

  return (
    <div className={styles.matchCard}>

      {/* ── Header ── */}
      <div className={styles.matchHeader}>
        <div className={styles.matchHeaderLeft}>
          <span className={styles.matchNum}>{index + 1}.</span>
          <span className={`${styles.matchKindBadge} ${kindBadgeCls}`}>{label}</span>
        </div>
        <span className={styles.matchSimPill}>{match.match_percentage.toFixed(1)}% similarity</span>
      </div>

      {/* ── Side-by-side comparison ── */}
      <div className={styles.matchBody}>

        {/* Left: your text */}
        <div className={styles.matchCol}>
          <p className={styles.blockLabel}>Your text</p>
          <div className={styles.docTextBlock}>
            <HighlightedText
              text={match.query_text}
              phrases={phrases}
              isExact={severity === 'identical'}
            />
          </div>
        </div>

        {/* Right: matched source */}
        {match.db_text ? (
          <div className={styles.matchCol}>
            <p className={styles.blockLabel}>Matched source</p>
            <div className={styles.sourceTextBlock}>
              {match.db_text}
            </div>
          </div>
        ) : (
          <div className={styles.matchCol} />
        )}

        {/* Exact phrases — spans both columns */}
        {phrases.length > 0 && (
          <div className={styles.phrasesBlock}>
            <p className={`${styles.blockLabel} ${labelCls}`}>Exact phrases</p>
            <div className={styles.phraseChips}>
              {phrases.map((ph, i) => (
                <span key={ph || i} className={`${styles.phrase} ${phraseCls}`}>
                  "{ph}"
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default function ReportPage() {
  "use no memo"

  const navigate = useNavigate()
  const [stored, setStored]               = useState<StoredReport | null>(null)
  const [expanded, setExpanded]           = useState<number | null>(0)
  const [showMinorSources, setShowMinorSources] = useState(false)
  const detailsRef  = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const arcRef       = useRef<SVGCircleElement>(null)
  const scoreNumRef  = useRef<HTMLSpanElement>(null)

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

  useGSAP(() => {
    if (!stored) return
    const sim  = stored.report.global_plagiarism_score_percent ?? 0
    const r    = 68
    const circ = 2 * Math.PI * r

    gsap.fromTo('[data-gsap="cover"]',
      { opacity: 0, y: 24 },
      { opacity: 1, y: 0, duration: 0.6, ease: 'power3.out' }
    )
    gsap.fromTo('[data-gsap="cover-badge"]',
      { opacity: 0, y: -6 },
      { opacity: 1, y: 0, duration: 0.4, ease: 'power2.out', delay: 0.18 }
    )

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

    gsap.fromTo('[data-gsap="stat-card"]',
      { opacity: 0, y: 14 },
      { opacity: 1, y: 0, duration: 0.42, stagger: 0.09, ease: 'power2.out', delay: 0.28 }
    )
    gsap.fromTo('[data-gsap="table-row"]',
      { opacity: 0, x: -10 },
      { opacity: 1, x: 0, duration: 0.3, stagger: 0.055, ease: 'power2.out', delay: 0.5 }
    )
  }, { scope: containerRef, dependencies: [stored] })

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

  const R    = 68
  const circ = 2 * Math.PI * R

  // ── Source splitting ────────────────────────────────────────────────────────
  const THRESHOLD    = 2
  const majorSources = sources.filter(src => {
    const contrib = src.score_contribution_percent ?? src.average_similarity_percent
    return contrib >= THRESHOLD
  })
  const minorSources = sources.filter(src => {
    const contrib = src.score_contribution_percent ?? src.average_similarity_percent
    return contrib < THRESHOLD
  })

  function renderTableRow(src: EngineSource, originalIdx: number) {
    const sev         = _srcTopSeverity(src)
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
        onClick={() => scrollToSource(originalIdx)}
        onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && scrollToSource(originalIdx)}
      >
        <span className={`${styles.badge} ${tblBadgeCls}`}>{tblLabel}</span>
        <div className={styles.srcCell}>
          <span className={styles.srcTitle}>{originalIdx + 1}.&nbsp;&nbsp;{src.title || src.arxiv_id}</span>
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
  }

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

          {/* ══ COVER ══ */}
          <section className={styles.cover} data-gsap="cover">
            <div className={styles.scoreHero}>

              <div className={styles.ringWrap}>
                <svg width="168" height="168" viewBox="0 0 168 168" className={styles.ringsvg}>
                  <circle cx="84" cy="84" r={R} fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth="10" />
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
                <div className={styles.ringCenter}>
                  <span className={styles.ringScore} style={{ color: sCol }}>
                    <span ref={scoreNumRef}>0</span>%
                  </span>
                  <span className={styles.ringLabel}>Similarity</span>
                </div>
              </div>

              <div className={styles.heroRight}>
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

            {/* ── Sources table with major/minor split ── */}
            {sources.length > 0 && (
              <div className={styles.sourcesTable}>
                <p className={styles.sectionHeading}>Matched Sources</p>
                <div className={styles.tableHead}>
                  <span>TYPE</span>
                  <span style={{ flex: 1 }}>SOURCE</span>
                  <span>MATCHES</span>
                  <span>DOC COVERAGE</span>
                </div>

                {/* Major sources — always visible */}
                {majorSources.map(src => renderTableRow(src, sources.indexOf(src)))}

                {/* Minor sources — collapsed by default */}
                {minorSources.length > 0 && (
                  <>
                    {showMinorSources && minorSources.map(src => renderTableRow(src, sources.indexOf(src)))}
                    <button
                      type="button"
                      className={styles.minorToggle}
                      onClick={() => setShowMinorSources(v => !v)}
                    >
                      {showMinorSources
                        ? `↑ Hide ${minorSources.length} minor source${minorSources.length !== 1 ? 's' : ''}`
                        : `↓ ${minorSources.length} minor source${minorSources.length !== 1 ? 's' : ''} with <${THRESHOLD}% coverage`}
                    </button>
                  </>
                )}
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

          {/* ══ SUBMITTED DOCUMENT ══ */}
          <section className={styles.docSection}>
            <div className={styles.screenOnly}>
              <PdfViewer
                pdfUrl={pdfUrl}
                authToken={authToken}
                phrases={phrases}
                onPhraseClick={scrollToSource}
              />
            </div>
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

          {/* ══ SOURCE DETAIL SECTIONS ══ */}
          {sources.length > 0 && (
            <div ref={detailsRef}>
              <p className={styles.sectionHeading} style={{ marginBottom: 12 }}>SIMILARITY DETAILS</p>

              {sources.map((src, si) => {
                const sev      = _srcTopSeverity(src)
                const numCls   = sev === 'identical'      ? styles.numExact
                               : sev === 'highly_similar' ? styles.numSimilar
                               :                            styles.numPara
                const badgeCls = sev === 'identical'      ? styles.badgeExact
                               : sev === 'highly_similar' ? styles.badgeSimilar
                               :                            styles.badgePara
                const sevLabel = sev === 'identical'      ? 'EXACT COPY'
                               : sev === 'highly_similar' ? 'HIGHLY SIMILAR'
                               :                            'PARAPHRASE'
                const contrib    = src.score_contribution_percent
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