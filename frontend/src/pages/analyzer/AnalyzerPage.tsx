import { useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { generatePdfReport, type ReportFilter } from '../../utils/report'
import { useDocumentAnalysis } from './hooks/useDocumentAnalysis'
import ScoreRing from './components/ScoreRing'
import MorphIcon, { type MorphPhase } from '../../components/ui/MorphIcon'
import MagneticButton from '../../components/ui/MagneticButton'
import { useTilt } from '../../hooks/useTilt'
import styles from './Analyzer.module.css'
import { REPORT_STORAGE_KEY, type StoredReport } from '../report/ReportPage'

gsap.registerPlugin(ScrollTrigger)
 
const STEPS = [
  { label: 'Uploading file'        },
  { label: 'Extracting text'       },
  { label: 'Chunking paragraphs'   },
  { label: 'Generating embeddings' },
  { label: 'Searching index'       },
  { label: 'Ranking sources'       },
]
 
export default function AnalyzerPage() {
  // useTilt accesses refs via contextSafe; handleReDownload has try/finally
  // without catch — React Compiler can't optimize this component, opt out.
  "use no memo"

  const navigate       = useNavigate()
  const analysis       = useDocumentAnalysis()
  const inputRef       = useRef<HTMLInputElement>(null)
  const sourceListRef  = useRef<HTMLDivElement>(null)
  const doneRef        = useRef<HTMLDivElement>(null)
  const [downloading,  setDownloading]  = useState(false)
  const [reportFilter, setReportFilter] = useState<ReportFilter>('all')

  // 3-D tilt on the upload card
  const tilt = useTilt<HTMLDivElement>(8)

  // Derive the icon phase from analysis state
  const morphPhase: MorphPhase = (() => {
    if (analysis.stage === 'error')     return 'error'
    if (analysis.stage === 'done')      return 'done'
    if (analysis.stage === 'uploading') return 'uploading'
    if (analysis.stage === 'analyzing') return 'analyzing'
    return 'idle'
  })()

  // Animate source rows in when the done view mounts
  useGSAP(() => {
    if (analysis.stage !== 'done') return
    const rows = sourceListRef.current?.querySelectorAll('[data-source-row]')
    if (!rows?.length) return
    gsap.fromTo(
      rows,
      { opacity: 0, y: 28, filter: 'blur(6px)' },
      {
        opacity: 1,
        y: 0,
        filter: 'blur(0px)',
        stagger: 0.06,
        duration: 0.7,
        ease: 'power3.out',
        delay: 0.3,
        clearProps: 'filter',
      }
    )
    // Hero metrics count up
    const doneHero = doneRef.current?.querySelector('[data-done-hero]')
    if (doneHero) {
      gsap.from(doneHero, { opacity: 0, y: 20, duration: 0.6, ease: 'power3.out' })
    }
  }, { dependencies: [analysis.stage], scope: doneRef })
 
  function handleViewReport() {
    if (!analysis.report || !analysis.docInfo) return
    const stored: StoredReport = {
      report:     analysis.report,
      filename:   analysis.docInfo.filename,
      date:       new Date().toLocaleString('en-GB'),
      documentId: analysis.docInfo.documentId,
    }
    sessionStorage.setItem(REPORT_STORAGE_KEY, JSON.stringify(stored))
    navigate('/report')
  }

  const { setDragging, acceptFile, analyze, reset } = analysis

  function onDragOver(e: React.DragEvent) {
    e.preventDefault()
    setDragging(true)
  }
 
  function onDragLeave() {
    setDragging(false)
  }
 
  function onDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) acceptFile(f)
  }
 
  async function handleReDownload() {
    if (!analysis.report || !analysis.docInfo) return
    setDownloading(true)
    try {
      await generatePdfReport(analysis.report, analysis.docInfo.filename, reportFilter)
    } catch {
      // swallow — download failure is non-critical
    }
    setDownloading(false)
  }
 
  const { file, dragging, stage, pipeStep, report, docInfo, errorMsg, isRunning } = analysis

  return (
    <div className={styles.page}>
      <main className={styles.main}>

        {/* ── Result view ── */}
        {stage === 'done' && report && docInfo ? (
          <div ref={doneRef} className={styles.doneWrap}>
            <div className={styles.doneHero} data-done-hero>
              <ScoreRing pct={report.global_plagiarism_score_percent} />
              <div>
                <h1 className={styles.doneHeadline}>Analysis complete</h1>
                <p className={styles.doneFilename}>{docInfo.filename}</p>
                {docInfo.processingTime != null && (
                  <p className={styles.doneTime}>Processed in {docInfo.processingTime.toFixed(1)}s</p>
                )}
                <div className={styles.doneStats}>
                  {[
                    { v: `${(report.global_plagiarism_score_percent ?? 0).toFixed(1)}%`, k: 'Similarity' },
                    { v: String(report.total_reported_sources ?? report.sources?.length ?? 0),          k: 'Sources'  },
                    { v: (report.document_stats?.total_words ?? 0).toLocaleString(),                    k: 'Words'    },
                  ].map(s => (
                    <div key={s.k} className={styles.doneStat}>
                      <span className={styles.doneStatV}>{s.v}</span>
                      <span className={styles.doneStatK}>{s.k}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className={styles.downloadNotice}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
              {downloading ? 'Generating PDF report…' : 'PDF report downloaded automatically.'}
            </div>

            <button type="button" className={styles.viewReportBtn} onClick={handleViewReport}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
              View full report online
            </button>

            <div className={styles.redownloadBar}>
              <span className={styles.rdLabel}>Download with filter:</span>
              <div className={styles.filterPills}>
                {(['all', 'exact', 'paraphrase'] as ReportFilter[]).map(f => (
                  <button key={f} type="button"
                    className={`${styles.pill} ${reportFilter === f ? styles.pillActive : ''}`}
                    onClick={() => setReportFilter(f)}>
                    {f === 'all' ? 'All matches' : f === 'exact' ? 'Exact only' : 'Paraphrase only'}
                  </button>
                ))}
              </div>
              <button type="button" className={styles.dlBtn} onClick={handleReDownload} disabled={downloading}>
                {downloading
                  ? <span className={styles.dlSpin}/>
                  : <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>}
                {downloading ? 'Generating…' : 'Download PDF'}
              </button>
            </div>

            {(report.sources?.length ?? 0) > 0 ? (
              <div ref={sourceListRef} className={styles.sourceTable}>
                <div className={styles.sourceTableHead}>
                  <span>Type</span><span style={{ flex: 1 }}>Source</span>
                  <span>Matches</span><span>Coverage</span>
                </div>
                {report.sources.map((src, i) => (
                  <div key={src.arxiv_id} className={styles.sourceRow} data-source-row style={{ animationDelay: `${i * 40}ms` }}>
                    <span className={`${styles.typePill} ${src.has_exact_copies ? styles.typePillExact : styles.typePillPara}`}>
                      {src.has_exact_copies ? 'Exact' : 'Para.'}
                    </span>
                    <div className={styles.srcInfo}>
                      <span className={styles.srcTitle}>{src.title || src.arxiv_id}</span>
                      <a href={`https://arxiv.org/abs/${src.arxiv_id}`} target="_blank"
                         rel="noopener noreferrer" className={styles.srcLink}>
                        arxiv.org/abs/{src.arxiv_id} ↗
                      </a>
                    </div>
                    <span className={styles.srcMatches}>{src.match_count}</span>
                    <span className={styles.srcPct}
                      style={{ color: (src.score_contribution_percent ?? src.average_similarity_percent) > 40 ? '#dc2626'
                                    : (src.score_contribution_percent ?? src.average_similarity_percent) > 15 ? '#d97706' : '#16a34a' }}>
                      {(src.score_contribution_percent ?? src.average_similarity_percent).toFixed(1)}%
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className={styles.noSources}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#16a34a" strokeWidth="2.5" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
                <div>
                  <p className={styles.noSourcesTitle}>No matches found</p>
                  <p className={styles.noSourcesSub}>Your document appears to be original.</p>
                </div>
              </div>
            )}

            <button type="button" className={styles.resetBtn} onClick={reset}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-3.51"/></svg>
              Check another document
            </button>
          </div>

        ) : (
          /* ── Upload / analyzing view ── */
          <div className={styles.uploadWrap}>
            {/* useTilt gives a subtle 3-D perspective tilt on hover */}
            <div
              className={styles.uploadCard}
              ref={tilt.ref}
              onMouseMove={tilt.onMouseMove}
              onMouseLeave={tilt.onMouseLeave}
            >
              <div className={styles.uploadHeading}>
                <div className={styles.uploadBadge}>
                  <span className={styles.badgeDot}/>ML-powered detection
                </div>
                <h1 className={styles.uploadTitle}>Check your document</h1>
                <p className={styles.uploadSub}>
                  Upload a PDF, DOCX, or TXT. Sentinel scans for exact matches and
                  paraphrased content. A PDF report downloads automatically.
                </p>
              </div>

              {!isRunning && (
                <>
                  {/* Hidden file input — shared by both states below */}
                  <input ref={inputRef} type="file" accept=".pdf,.docx,.txt"
                    style={{ display: 'none' }}
                    onChange={e => e.target.files?.[0] && acceptFile(e.target.files[0])} />

                  {file ? (
                    // File selected: plain div so the clear <button> is not nested
                    // inside another interactive element (invalid HTML).
                    <div
                      className={`${styles.dropZone} ${styles.dropZoneFile}`}
                      onDragOver={onDragOver} onDragLeave={onDragLeave} onDrop={onDrop}
                    >
                      <div className={styles.fileRow}>
                        <div className={styles.fileExt}>{file.name.split('.').pop()?.toUpperCase()}</div>
                        <div className={styles.fileDetails}>
                          <span className={styles.fileName}>{file.name}</span>
                          <span className={styles.fileSize}>{(file.size / 1024).toFixed(1)} KB</span>
                        </div>
                        <button type="button" className={styles.clearBtn} aria-label="Remove selected file"
                          onClick={() => reset()}>
                          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                        </button>
                      </div>
                    </div>
                  ) : (
                    // No file: real <button> — no nested interactive elements.
                    <button
                      type="button"
                      className={`${styles.dropZone} ${dragging ? styles.dropZoneActive : ''}`}
                      onDragOver={onDragOver} onDragLeave={onDragLeave} onDrop={onDrop}
                      onClick={() => inputRef.current?.click()}
                      aria-label="Upload document — click or drop a file here"
                    >
                      <div className={styles.dropEmpty}>
                        {/* MorphIcon replaces the static SVG — shows upload or drag state */}
                        <div className={styles.dropIcon}>
                          <MorphIcon
                            phase={dragging ? 'uploading' : 'idle'}
                            size={38}
                          />
                        </div>
                        <p className={styles.dropTitle}>Drop your document here</p>
                        <p className={styles.dropSub}>or <span className={styles.dropLink}>click to browse</span></p>
                        <div className={styles.dropFormats}><span>PDF</span><span>·</span><span>DOCX</span><span>·</span><span>TXT</span></div>
                      </div>
                    </button>
                  )}
                </>
              )}

              {isRunning && (() => {
                const stepIndex  = stage === 'uploading' ? 0 : pipeStep
                const stepLabel  = STEPS[stepIndex]?.label ?? STEPS[0].label
                const stepNum    = Math.min(stepIndex + 1, STEPS.length)
                return (
                  <div className={styles.pipeline}>
                    {/* Status header — MorphIcon replaces the CSS spinner */}
                    <div className={styles.pipeHeader}>
                      <MorphIcon
                        phase={stage === 'uploading' ? 'uploading' : 'analyzing'}
                        size={22}
                      />
                      <span>{stage === 'uploading' ? 'Uploading…' : 'Analyzing document…'}</span>
                    </div>

                    {/* Current step — large, animated on change */}
                    <div className={styles.pipeStatus}>
                      <span key={`${stage}-${stepIndex}`} className={styles.pipeStatusLabel}>
                        {stepLabel}
                      </span>
                      <span className={styles.pipeCounter}>
                        Step {stepNum} of {STEPS.length}
                      </span>
                    </div>

                    {/* Progress segments — one per step */}
                    <div className={styles.pipeSteps}>
                      {STEPS.map((_, i) => {
                        const done   = stage === 'analyzing' && i < stepIndex
                        const active = i === stepIndex
                        return (
                          <div
                            key={i}
                            className={[
                              styles.step,
                              done   ? styles.stepDone   : '',
                              active ? styles.stepActive : '',
                            ].join(' ')}
                          />
                        )
                      })}
                    </div>

                    <p className={styles.pipeNote}>PDF report will download automatically when complete.</p>
                  </div>
                )
              })()}

              {stage === 'error' && (
                <div className={styles.errorBox}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                  {errorMsg}
                </div>
              )}

              {file && !isRunning && (
                /* MagneticButton: inner content follows cursor; springs back on leave */
                <MagneticButton className={styles.analyzeBtn} onClick={analyze}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                  Run plagiarism check
                </MagneticButton>
              )}

              {!file && !isRunning && stage !== 'error' && (
                <p className={styles.uploadNote}>Max 20 MB · Results in under a minute</p>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  )
}