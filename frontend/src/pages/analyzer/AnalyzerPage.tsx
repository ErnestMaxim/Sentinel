import { useState, useRef, useCallback } from 'react'
import Navbar from '../../components/shared/navbar/Navbar'
import styles from './Analyzer.module.css'
import { generateReport } from '../../utils/generateReport'

// ─────────────────────────────────────────────────────────────────────────────
// Types — mirror the engine's actual JSON output shape
// ─────────────────────────────────────────────────────────────────────────────

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
}

interface EngineSource {
  arxiv_id:                   string
  title:                      string
  match_count:                number
  average_similarity_percent: number
  has_exact_copies:           boolean
  matches:                    EngineMatch[]
}

interface EngineReport {
  file_name:                      string
  global_plagiarism_score_percent: number
  total_suspicious_sources:       number
  total_reported_sources:         number
  document_stats: {
    total_words:           number
    total_chunks_analyzed: number
  }
  analysis_config: {
    threshold_used:    number
    embedding_model:   string
    category_routing:  { enabled: boolean; routed_to: string[] | null }
  }
  sources: EngineSource[]
}

// Wrapped in the DocumentResponse (report_data field holds the engine output)
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

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api'

const PIPELINE_STEPS = [
  { key: 'uploading',  label: 'Uploading file'         },
  { key: 'extracting', label: 'Extracting text'        },
  { key: 'chunking',   label: 'Chunking paragraphs'    },
  { key: 'embedding',  label: 'Generating embeddings'  },
  { key: 'searching',  label: 'Searching FAISS index'  },
  { key: 'ranking',    label: 'Ranking sources'        },
]

// ─────────────────────────────────────────────────────────────────────────────
// Score ring
// ─────────────────────────────────────────────────────────────────────────────

function ScoreRing({ pct }: { pct: number | undefined }) {
  const r = 70
  const circ = 2 * Math.PI * r
  const originality = 100 - (pct ?? 0)
  const dash  = (originality / 100) * circ
  const color = originality >= 75 ? '#4ade80' : originality >= 50 ? '#FFDC00' : '#f87171'
  return (
    <div className={styles.scoreRing}>
      <svg width="176" height="176" viewBox="0 0 176 176">
        <circle cx="88" cy="88" r={r} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="8" />
        <circle
          cx="88" cy="88" r={r} fill="none"
          stroke={color} strokeWidth="8" strokeLinecap="round"
          strokeDasharray={`${dash} ${circ}`} strokeDashoffset={circ / 4}
          style={{ transition: 'stroke-dasharray 1.2s cubic-bezier(0.4,0,0.2,1)', filter: `drop-shadow(0 0 10px ${color}70)` }}
        />
      </svg>
      <div className={styles.scoreCenter}>
        <span className={styles.scoreNum} style={{ color }}>{originality.toFixed(0)}%</span>
        <span className={styles.scoreLabel}>original</span>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Main page
// ─────────────────────────────────────────────────────────────────────────────

export default function AnalyzerPage() {
  const [file, setFile]           = useState<File | null>(null)
  const [dragging, setDragging]   = useState(false)
  const [stage, setStage]         = useState<Stage>('idle')
  const [pipeStep, setPipeStep]   = useState(0)        // 0-5 during analysis
  const [report, setReport]       = useState<EngineReport | null>(null)
  const [docInfo, setDocInfo]     = useState<{ filename: string; processingTime: number | null } | null>(null)
  const [errorMsg, setErrorMsg]   = useState('')
  const [expanded, setExpanded]   = useState<string | null>(null)
  const [downloading, setDownloading] = useState(false)
  const inputRef                  = useRef<HTMLInputElement>(null)

  // ── drag-and-drop ──────────────────────────────────────────────────────────
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

  // ── submit ─────────────────────────────────────────────────────────────────
  async function handleAnalyze() {
    if (!file) return
    setReport(null); setErrorMsg(''); setPipeStep(0)

    try {
      // ── Step 1: upload ────────────────────────────────────────────────────
      setStage('uploading')
      const token = localStorage.getItem('access_token')

      const formData = new FormData()
      formData.append('file', file)
      formData.append('user_id', '1')   // swap for real user id from AuthContext

      const uploadRes = await fetch(`${API}/documents/upload`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      })

      if (!uploadRes.ok) {
        const err = await uploadRes.json().catch(() => ({ detail: 'Upload failed' }))
        throw new Error(err.detail ?? 'Upload failed')
      }

      const doc: DocumentResponse = await uploadRes.json()

      // ── Step 2: animate pipeline while engine runs ────────────────────────
      setStage('analyzing')

      // Animate steps 1-5 at a fake cadence; the real work is the fetch below
      const animatePipeline = async () => {
        for (let i = 1; i <= 5; i++) {
          await new Promise(r => setTimeout(r, 1100 + Math.random() * 700))
          setPipeStep(i)
        }
      }

      const analyzeRes = fetch(`${API}/documents/${doc.id}/analyze`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })

      await Promise.all([analyzeRes, animatePipeline()])

      const analysisResponse = await (await analyzeRes)
      if (!analysisResponse.ok) {
        const err = await analysisResponse.json().catch(() => ({ detail: 'Analysis failed' }))
        throw new Error(err.detail ?? 'Analysis failed')
      }

      const analyzedDoc: DocumentResponse = await analysisResponse.json()

      if (!analyzedDoc.report?.report_data) {
        throw new Error('Engine returned no report data.')
      }

      setReport(analyzedDoc.report.report_data)
      setDocInfo({
        filename:       analyzedDoc.filename,
        processingTime: analyzedDoc.report.processing_time_seconds ?? null,
      })
      setStage('done')

    } catch (e: unknown) {
      setErrorMsg(e instanceof Error ? e.message : 'Something went wrong.')
      setStage('error')
    }
  }

  async function handleDownload() {
    if (!report || !docInfo) return
    setDownloading(true)
    try {
      await generateReport(report, docInfo.filename)
    } finally {
      setDownloading(false)
    }
  }

  const isRunning = stage === 'uploading' || stage === 'analyzing'

  // ── render ─────────────────────────────────────────────────────────────────
  return (
    <div className={styles.page}>
      <Navbar />
      <main className={styles.main}>

        {/* ══ RESULTS ════════════════════════════════════════════════════════ */}
        {stage === 'done' && report ? (
          <div className={styles.resultsView}>

            {/* top bar */}
            <div className={styles.resultsTopBar}>
              <div>
                <h1 className={styles.resultsTitle}>Analysis complete</h1>
                <p className={styles.resultsFile}>
                  {docInfo?.filename}
                  {docInfo?.processingTime != null && (
                    <span className={styles.processingTime}> · {docInfo.processingTime?.toFixed(1)}s</span>
                  )}
                </p>
              </div>
              <div className={styles.topBarActions}>
                <button className={styles.downloadBtn} onClick={handleDownload} disabled={downloading}>
                  {downloading ? (
                    <span className={styles.dlSpinner} />
                  ) : (
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                      <polyline points="7 10 12 15 17 10"/>
                      <line x1="12" y1="15" x2="12" y2="3"/>
                    </svg>
                  )}
                  {downloading ? 'Generating…' : 'Download report'}
                </button>
                <button className={styles.rerunBtn} onClick={() => { setStage('idle'); setReport(null); setFile(null) }}>
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-3.51"/></svg>
                  New check
                </button>
              </div>
            </div>

            {/* score + stats */}
            <div className={styles.scoreRow}>
              <ScoreRing pct={report.global_plagiarism_score_percent} />
              <div className={styles.statsGrid}>
                {[
                  { val: `${(report.global_plagiarism_score_percent ?? 0).toFixed(1)}%`, key: 'similarity',     accent: '#f87171' },
                  { val: report.document_stats?.total_chunks_analyzed ?? 0,        key: 'chunks analyzed' },
                  { val: report.document_stats?.total_words ?? 0,                  key: 'total words'    },
                  { val: report.total_reported_sources ?? report.sources?.length ?? 0, key: 'sources found'  },
                ].map(s => (
                  <div key={s.key} className={styles.statCard}>
                    <span className={styles.statVal} style={s.accent ? { color: s.accent } : {}}>{s.val}</span>
                    <span className={styles.statKey}>{s.key}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* analysis config badge row */}
            <div className={styles.configRow}>
              <span className={styles.configChip}>threshold {report.analysis_config?.threshold_used ?? '—'}</span>
              <span className={styles.configChip}>{report.analysis_config?.embedding_model ?? '—'}</span>
              {report.analysis_config?.category_routing?.enabled && report.analysis_config?.category_routing?.routed_to?.length && (
                <span className={styles.configChip}>
                  routed → {report.analysis_config?.category_routing?.routed_to?.join(', ')}
                </span>
              )}
            </div>

            {/* sources */}
            {(report.sources?.length ?? 0) === 0 ? (
              <div className={styles.noSources}>
                <div className={styles.noSourcesIcon}>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
                </div>
                <div>
                  <p className={styles.noSourcesTitle}>No matches found</p>
                  <p className={styles.noSourcesSub}>Your document appears to be original.</p>
                </div>
              </div>
            ) : (
              <div className={styles.sourceList}>
                <h2 className={styles.sourcesHeading}>
                  Matched sources
                  <span className={styles.sourcesBadge}>{report.sources?.length ?? 0}</span>
                </h2>

                {(report.sources ?? []).map((src, si) => (
                  <div key={src.arxiv_id} className={styles.sourceCard} style={{ animationDelay: `${si * 55}ms` }}>
                    <button
                      className={styles.sourceHeader}
                      onClick={() => setExpanded(expanded === src.arxiv_id ? null : src.arxiv_id)}
                    >
                      <div className={styles.sourceHeaderLeft}>
                        <span className={`${styles.badge} ${src.has_exact_copies ? styles.badgeRed : styles.badgeAmber}`}>
                          {src.has_exact_copies ? 'Exact copy' : 'Paraphrase'}
                        </span>
                        <span className={styles.srcTitle}>{src.title}</span>
                        <span className={styles.srcId}>{src.arxiv_id}</span>
                      </div>
                      <div className={styles.sourceHeaderRight}>
                        <span className={styles.srcPct}>{(src.average_similarity_percent ?? 0).toFixed(1)}%</span>
                        <span className={styles.srcCount}>{src.match_count} match{src.match_count !== 1 ? 'es' : ''}</span>
                        <svg
                          className={`${styles.srcChevron} ${expanded === src.arxiv_id ? styles.srcChevronOpen : ''}`}
                          width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                          strokeWidth="2.5" strokeLinecap="round"><polyline points="6 9 12 15 18 9"/>
                        </svg>
                      </div>
                    </button>

                    {expanded === src.arxiv_id && (
                      <div className={styles.matchList}>
                        {src.matches.map((m, i) => (
                          <div key={i} className={styles.matchItem}>
                            <div className={styles.matchMeta}>
                              <span className={styles.matchPct}>{(m.match_percentage ?? 0).toFixed(0)}%</span>
                              <div className={styles.matchTrack}>
                                <div className={styles.matchFill} style={{ width: `${m.match_percentage}%` }} />
                              </div>
                            </div>
                            {/* Show the flagged chunk from the uploaded doc */}
                            <p className={styles.matchLabel}>Your text</p>
                            <p className={styles.matchText}>{m.query_text}</p>
                            {/* Optionally show the matching DB text */}
                            {m.db_text && (
                              <>
                                <p className={styles.matchLabel}>Matched source text</p>
                                <p className={`${styles.matchText} ${styles.matchTextDb}`}>{m.db_text}</p>
                              </>
                            )}
                            {m.exact_copied_phrases.length > 0 && (
                              <div className={styles.phraseList}>
                                {m.exact_copied_phrases.map((ph, j) => (
                                  <span key={j} className={styles.phrase}>"{ph}"</span>
                                ))}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

        ) : (
          /* ══ UPLOAD VIEW ═════════════════════════════════════════════════ */
          <div className={styles.uploadView}>

            {/* left hero */}
            <div className={styles.heroCol}>
              <div className={styles.heroPill}>
                <span className={styles.heroPillDot} />
                ML-powered detection
              </div>
              <h1 className={styles.heroTitle}>
                Check your<br />
                <span className={styles.heroAccent}>document</span>
              </h1>
              <p className={styles.heroBody}>
                Upload a PDF, DOCX, or TXT. Sentinel chunks your text, generates
                semantic embeddings, and scans our academic index for matches.
              </p>
              <div className={styles.featureList}>
                {[
                  'Catches paraphrasing via semantic similarity',
                  'Exact phrase detection across sources',
                  'Full per-source match breakdown',
                ].map(f => (
                  <div key={f} className={styles.featureRow}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#FFDC00" strokeWidth="2.5" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
                    <span>{f}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* right upload card */}
            <div className={styles.uploadCol}>
              <div className={styles.uploadCard}>

                {/* drop zone — hidden while running */}
                {!isRunning && (
                  <div
                    className={`${styles.dropZone} ${dragging ? styles.dzActive : ''}`}
                    onDragOver={onDragOver} onDragLeave={onDragLeave} onDrop={onDrop}
                    onClick={() => inputRef.current?.click()}
                    role="button" tabIndex={0}
                    onKeyDown={e => e.key === 'Enter' && inputRef.current?.click()}
                  >
                    <input ref={inputRef} type="file" accept=".pdf,.docx,.txt"
                      className={styles.hiddenInput}
                      onChange={e => e.target.files?.[0] && acceptFile(e.target.files[0])} />

                    {!file ? (
                      <div className={styles.dzEmpty}>
                        <div className={styles.dzIconRing}>
                          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                            <polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>
                          </svg>
                        </div>
                        <p className={styles.dzTitle}>Drop file here</p>
                        <p className={styles.dzSub}>or <span className={styles.dzBrowse}>click to browse</span></p>
                        <div className={styles.dzTags}><span>PDF</span><span>DOCX</span><span>TXT</span></div>
                      </div>
                    ) : (
                      <div className={styles.dzFilledInner}>
                        <div className={styles.fileCard}>
                          <div className={styles.fileExt}>{file.name.split('.').pop()?.toUpperCase()}</div>
                          <div className={styles.fileInfo}>
                            <span className={styles.fileName}>{file.name}</span>
                            <span className={styles.fileSize}>{(file.size / 1024).toFixed(1)} KB</span>
                          </div>
                          <button className={styles.clearBtn}
                            onClick={e => { e.stopPropagation(); setFile(null); setStage('idle') }}>
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* pipeline progress */}
                {isRunning && (
                  <div className={styles.pipeline}>
                    <p className={styles.pipelineTitle}>
                      <span className={styles.pipeSpinner} />
                      {stage === 'uploading' ? 'Uploading…' : 'Analyzing…'}
                    </p>
                    <div className={styles.pipeSteps}>
                      {PIPELINE_STEPS.map((s, i) => {
                        const done   = stage === 'analyzing' ? (i === 0 || i < pipeStep) : false
                        const active = stage === 'uploading' ? i === 0 : i === pipeStep
                        return (
                          <div key={s.key} className={`${styles.pipeStep} ${done ? styles.psDone : ''} ${active ? styles.psActive : ''}`}>
                            <div className={styles.psDot}>
                              {done
                                ? <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
                                : active ? <span className={styles.psPulse} /> : null}
                            </div>
                            {i < PIPELINE_STEPS.length - 1 && <div className={`${styles.psLine} ${done ? styles.psLineDone : ''}`} />}
                            <span className={styles.psLabel}>{s.label}</span>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}

                {/* error */}
                {stage === 'error' && (
                  <div className={styles.errorBox}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                    {errorMsg}
                  </div>
                )}

                {/* CTA */}
                {file && !isRunning && (
                  <button className={styles.analyzeBtn} onClick={handleAnalyze}>
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                    Run plagiarism check
                  </button>
                )}

                {!file && !isRunning && stage !== 'error' && (
                  <p className={styles.uploadNote}>Max 20 MB · Results in under a minute</p>
                )}
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}