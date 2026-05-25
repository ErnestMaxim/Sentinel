import { useState, useRef, useCallback } from 'react'
import Navbar from '../../components/shared/navbar/Navbar'
import styles from './Analyzer.module.css'
import { generatePdfReport, type ReportFilter } from '../../utils/generateReport'

// ── Types ─────────────────────────────────────────────────────────────────────

type Stage = 'idle' | 'uploading' | 'analyzing' | 'done' | 'error'

interface EngineMatch {
  query_chunk_idx:      number
  query_text:           string
  db_chunk_idx:         number
  db_text:              string
  cosine_similarity:    number
  match_percentage:     number
  exact_copied_phrases: string[]
  db_source_type:       string
  detection?:           'exact' | 'paraphrase'
}

interface EngineSource {
  arxiv_id:                    string
  title:                       string
  match_count:                 number
  average_similarity_percent:  number
  has_exact_copies:            boolean
  score_contribution_percent?: number
  matches:                     EngineMatch[]
}

interface EngineReport {
  file_name:                       string
  global_plagiarism_score_percent: number
  total_suspicious_sources:        number
  total_reported_sources:          number
  document_stats: {
    total_words:           number
    total_chunks_analyzed: number
  }
  analysis_config: {
    threshold_used:   number
    embedding_model:  string
    category_routing: { enabled: boolean; routed_to: string[] | null }
  }
  sources: EngineSource[]
}

interface DocumentResponse {
  id:         number
  filename:   string
  status:     string
  word_count: number | null
  report?: {
    id:                      number
    global_score:            number
    report_data:             EngineReport
    processing_time_seconds: number | null
    similarity_threshold:    number
    created_at:              string
  } | null
}

// ── Constants ──────────────────────────────────────────────────────────────────

const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api'

const STEPS = [
  { label: 'Uploading file'        },
  { label: 'Extracting text'       },
  { label: 'Chunking paragraphs'   },
  { label: 'Generating embeddings' },
  { label: 'Searching index'       },
  { label: 'Ranking sources'       },
]

// ── Score ring ────────────────────────────────────────────────────────────────

function ScoreRing({ pct }: { pct: number }) {
  const r    = 52
  const circ = 2 * Math.PI * r
  
  // Logic Fix: Default to 0 if the value is NaN or missing
  const safePct = isNaN(pct) || pct === null ? 0 : pct;
  const orig = 100 - safePct
  
  const dash = (orig / 100) * circ
  const col  = orig >= 75 ? '#16a34a' : orig >= 50 ? '#d97706' : '#dc2626'
  
  return (
    <div className={styles.ring}>
      <svg width="128" height="128" viewBox="0 0 128 128">
        <circle cx="64" cy="64" r={r} fill="none" stroke="#e5e7eb" strokeWidth="7"/>
        <circle cx="64" cy="64" r={r} fill="none" stroke={col} strokeWidth="7"
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circ}`}
          strokeDashoffset={circ / 4}
          style={{ transition: 'stroke-dasharray 1s ease' }}
        />
      </svg>
      <div className={styles.ringCenter}>
        {/* UI Fix: Display 100 if math fails */}
        <span className={styles.ringNum} style={{ color: col }}>
            {isNaN(orig) ? '100' : orig.toFixed(0)}%
        </span>
        <span className={styles.ringLabel}>original</span>
      </div>
    </div>
  )
}

// ── Main ───────────────────────────────────────────────────────────────────────

export default function AnalyzerPage() {
  const [file,          setFile]          = useState<File | null>(null)
  const [dragging,      setDragging]      = useState(false)
  const [stage,         setStage]         = useState<Stage>('idle')
  const [pipeStep,      setPipeStep]      = useState(0)
  const [report,        setReport]        = useState<EngineReport | null>(null)
  const [docInfo,       setDocInfo]       = useState<{ filename: string; processingTime: number | null } | null>(null)
  const [errorMsg,      setErrorMsg]      = useState('')
  const [downloading,   setDownloading]   = useState(false)
  const [reportFilter,  setReportFilter]  = useState<ReportFilter>('all')
  const inputRef = useRef<HTMLInputElement>(null)

  const isRunning = stage === 'uploading' || stage === 'analyzing'

  // ── File handling ─────────────────────────────────────────────────────────

  const onDragOver  = useCallback((e: React.DragEvent) => { e.preventDefault(); setDragging(true) }, [])
  const onDragLeave = useCallback(() => setDragging(false), [])
  const onDrop      = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setDragging(false)
    const f = e.dataTransfer.files[0]; if (f) acceptFile(f)
  }, [])

  function acceptFile(f: File) {
    const ok = f.name.endsWith('.pdf') || f.name.endsWith('.docx') || f.name.endsWith('.txt')
    if (!ok) { setErrorMsg('Only PDF, DOCX, or TXT files are supported.'); setStage('error'); return }
    setFile(f); setStage('idle'); setReport(null); setErrorMsg('')
  }

  // ── Analysis ──────────────────────────────────────────────────────────────

  async function handleAnalyze() {
    if (!file) return
    setReport(null); setErrorMsg(''); setPipeStep(0)

    try {
      setStage('uploading')
      const token = localStorage.getItem('access_token')

      // ── Resolve real user id from token ──────────────────────────────────
      const meRes = await fetch(`${API}/auth/me`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (!meRes.ok) throw new Error('Not authenticated')
      const me = await meRes.json()

      const formData = new FormData()
      formData.append('file', file)
      formData.append('user_id', String(me.id))

      const uploadRes = await fetch(`${API}/documents/upload`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      })
      if (!uploadRes.ok) {
        const err = await uploadRes.json().catch(() => ({}))
        throw new Error((err as any).detail ?? 'Upload failed')
      }
      const doc: DocumentResponse = await uploadRes.json()

      setStage('analyzing')
      const animatePipeline = async () => {
        for (let i = 1; i <= 5; i++) {
          await new Promise(r => setTimeout(r, 1100 + Math.random() * 700))
          setPipeStep(i)
        }
      }

      // ✅ KEY FIX: destructure the Response directly from Promise.all
      // so it is only awaited once — the old code double-awaited it
      const [analysisResponse] = await Promise.all([
        fetch(`${API}/documents/${doc.id}/analyze`, {
          method: 'POST',
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        }),
        animatePipeline(),
      ])

      if (!analysisResponse.ok) {
        const err = await analysisResponse.json().catch(() => ({}))
        throw new Error((err as any).detail ?? 'Analysis failed')
      }

      const analyzedDoc: DocumentResponse = await analysisResponse.json()
      if (!analyzedDoc.report?.report_data) {
        throw new Error('Engine returned no report data.')
      }

      setReport(analyzedDoc.report.report_data)
      setDocInfo({
        filename: analyzedDoc.filename,
        processingTime: analyzedDoc.report.processing_time_seconds ?? null,
      })
      setStage('done')

    } catch (e: unknown) {
      setErrorMsg(e instanceof Error ? e.message : 'Something went wrong.')
      setStage('error')
    }
  }

  async function handleReDownload() {
    if (!report || !docInfo) return
    setDownloading(true)
    try { await generatePdfReport(report, docInfo.filename, reportFilter) }
    finally { setDownloading(false) }
  }

  function reset() { setStage('idle'); setReport(null); setFile(null); setErrorMsg('') }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className={styles.page}>
      <Navbar />
      <main className={styles.main}>

        {/* ══════════════════════ DONE ══════════════════════════════════════ */}
        {stage === 'done' && report && docInfo ? (
          <div className={styles.doneWrap}>

            {/* ── Score + headline ── */}
            <div className={styles.doneHero}>
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
                    { v: String(report.total_reported_sources ?? report.sources?.length ?? 0), k: 'Sources' },
                    { v: (report.document_stats?.total_words ?? 0).toLocaleString(), k: 'Words' },
                  ].map(s => (
                    <div key={s.k} className={styles.doneStat}>
                      <span className={styles.doneStatV}>{s.v}</span>
                      <span className={styles.doneStatK}>{s.k}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* ── PDF downloaded notice ── */}
            <div className={styles.downloadNotice}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
              {downloading ? 'Generating PDF report…' : 'PDF report downloaded automatically.'}
            </div>

            {/* ── Re-download with filter ── */}
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
              <button className={styles.dlBtn} onClick={handleReDownload} disabled={downloading}>
                {downloading
                  ? <span className={styles.dlSpin}/>
                  : <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>}
                {downloading ? 'Generating…' : 'Download PDF'}
              </button>
            </div>

            {/* ── Sources list ── */}
            {(report.sources?.length ?? 0) > 0 && (
              <div className={styles.sourceTable}>
                <div className={styles.sourceTableHead}>
                  <span>Type</span>
                  <span style={{ flex: 1 }}>Source</span>
                  <span>Matches</span>
                  <span>Similarity</span>
                </div>
                {report.sources.map((src, i) => {
                  const isExact = src.has_exact_copies
                  return (
                    <div key={src.arxiv_id} className={styles.sourceRow}
                         style={{ animationDelay: `${i * 40}ms` }}>
                      <span className={`${styles.typePill} ${isExact ? styles.typePillExact : styles.typePillPara}`}>
                        {isExact ? 'Exact' : 'Para.'}
                      </span>
                      <div className={styles.srcInfo}>
                        <span className={styles.srcTitle}>{src.title || src.arxiv_id}</span>
                        <a href={`https://arxiv.org/abs/${src.arxiv_id}`}
                           target="_blank" rel="noopener noreferrer"
                           className={styles.srcLink}>
                          arxiv.org/abs/{src.arxiv_id} ↗
                        </a>
                      </div>
                      <span className={styles.srcMatches}>{src.match_count}</span>
                      <span className={styles.srcPct}
                            style={{ color: src.average_similarity_percent > 40 ? '#dc2626'
                                          : src.average_similarity_percent > 15 ? '#d97706' : '#16a34a' }}>
                        {src.average_similarity_percent.toFixed(1)}%
                      </span>
                    </div>
                  )
                })}
              </div>
            )}

            {/* ── No sources ── */}
            {(report.sources?.length ?? 0) === 0 && (
              <div className={styles.noSources}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#16a34a" strokeWidth="2.5" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
                <div>
                  <p className={styles.noSourcesTitle}>No matches found</p>
                  <p className={styles.noSourcesSub}>Your document appears to be original.</p>
                </div>
              </div>
            )}

            <button className={styles.resetBtn} onClick={reset}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-3.51"/></svg>
              Check another document
            </button>
          </div>

        ) : (
          /* ════════════════════ UPLOAD / ANALYZING ═════════════════════════ */
          <div className={styles.uploadWrap}>
            <div className={styles.uploadCard}>

              {/* Heading */}
              <div className={styles.uploadHeading}>
                <div className={styles.uploadBadge}>
                  <span className={styles.badgeDot}/>
                  ML-powered detection
                </div>
                <h1 className={styles.uploadTitle}>Check your document</h1>
                <p className={styles.uploadSub}>
                  Upload a PDF, DOCX, or TXT. Sentinel scans for exact matches and
                  paraphrased content. A PDF report downloads automatically.
                </p>
              </div>

              {/* Drop zone */}
              {!isRunning && (
                <div
                  className={`${styles.dropZone} ${dragging ? styles.dropZoneActive : ''} ${file ? styles.dropZoneFile : ''}`}
                  onDragOver={onDragOver} onDragLeave={onDragLeave} onDrop={onDrop}
                  onClick={() => inputRef.current?.click()}
                  role="button" tabIndex={0}
                  onKeyDown={e => e.key === 'Enter' && inputRef.current?.click()}
                >
                  <input ref={inputRef} type="file" accept=".pdf,.docx,.txt"
                    style={{ display: 'none' }}
                    onChange={e => e.target.files?.[0] && acceptFile(e.target.files[0])} />

                  {file ? (
                    <div className={styles.fileRow}>
                      <div className={styles.fileExt}>
                        {file.name.split('.').pop()?.toUpperCase()}
                      </div>
                      <div className={styles.fileDetails}>
                        <span className={styles.fileName}>{file.name}</span>
                        <span className={styles.fileSize}>{(file.size / 1024).toFixed(1)} KB</span>
                      </div>
                      <button className={styles.clearBtn}
                        onClick={e => { e.stopPropagation(); setFile(null); setStage('idle') }}>
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                      </button>
                    </div>
                  ) : (
                    <div className={styles.dropEmpty}>
                      <div className={styles.dropIcon}>
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                          <polyline points="17 8 12 3 7 8"/>
                          <line x1="12" y1="3" x2="12" y2="15"/>
                        </svg>
                      </div>
                      <p className={styles.dropTitle}>Drop your document here</p>
                      <p className={styles.dropSub}>or <span className={styles.dropLink}>click to browse</span></p>
                      <div className={styles.dropFormats}>
                        <span>PDF</span><span>DOCX</span><span>TXT</span>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Pipeline progress */}
              {isRunning && (
                <div className={styles.pipeline}>
                  <div className={styles.pipeHeader}>
                    <span className={styles.pipeSpinner}/>
                    <span>{stage === 'uploading' ? 'Uploading…' : 'Analyzing document…'}</span>
                  </div>
                  <div className={styles.pipeSteps}>
                    {STEPS.map((s, i) => {
                      const done   = stage === 'analyzing' && (i === 0 || i < pipeStep)
                      const active = stage === 'uploading' ? i === 0 : i === pipeStep
                      return (
                        <div key={i} className={`${styles.step} ${done ? styles.stepDone : ''} ${active ? styles.stepActive : ''}`}>
                          <div className={styles.stepDot}>
                            {done ? (
                              <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
                            ) : active ? (
                              <span className={styles.stepPulse}/>
                            ) : null}
                          </div>
                          {i < STEPS.length - 1 && (
                            <div className={`${styles.stepLine} ${done ? styles.stepLineDone : ''}`}/>
                          )}
                          <span className={styles.stepLabel}>{s.label}</span>
                        </div>
                      )
                    })}
                  </div>
                  <p className={styles.pipeNote}>PDF report will download automatically when complete.</p>
                </div>
              )}

              {/* Error */}
              {stage === 'error' && (
                <div className={styles.errorBox}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                  {errorMsg}
                </div>
              )}

              {/* Analyze button */}
              {file && !isRunning && (
                <button className={styles.analyzeBtn} onClick={handleAnalyze}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                  Run plagiarism check
                </button>
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