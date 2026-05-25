import { useState, useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import Navbar from '../../components/shared/navbar/Navbar'
import { generatePdfReport } from '../../utils/generateReport'
import styles from './HistoryPage.module.css'

// ── Types (mirrors DocumentResponse from AnalyzerPage) ───────────────────────

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
  sources: {
    arxiv_id:                   string
    title:                      string
    match_count:                number
    average_similarity_percent: number
    has_exact_copies:           boolean
    matches:                    unknown[]
  }[]
}

interface HistoryDocument {
  id:          number
  filename:    string
  status:      'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED'
  word_count:  number | null
  uploaded_at: string
  report?: {
    id:                      number
    global_score:            number
    report_data:             EngineReport
    processing_time_seconds: number | null
    similarity_threshold:    number
    created_at:              string
  } | null
}

// ── Constants ─────────────────────────────────────────────────────────────────

const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api'

// ── Helpers ───────────────────────────────────────────────────────────────────

function scoreClass(score: number): string {
  if (score <= 20) return styles.scoreLow
  if (score <= 50) return styles.scoreMid
  return styles.scoreHigh
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', {
    day:   '2-digit',
    month: 'short',
    year:  'numeric',
  })
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('en-GB', {
    day:    '2-digit',
    month:  'short',
    year:   'numeric',
    hour:   '2-digit',
    minute: '2-digit',
  })
}

// ── Sub-components ────────────────────────────────────────────────────────────

function FileIcon() {
  return (
    <div className={styles.fileIcon}>
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <polyline points="14 2 14 8 20 8"/>
        <line x1="16" y1="13" x2="8" y2="13"/>
        <line x1="16" y1="17" x2="8" y2="17"/>
        <polyline points="10 9 9 9 8 9"/>
      </svg>
    </div>
  )
}

function SkeletonRows() {
  return (
    <>
      {[1, 2, 3, 4].map(i => (
        <tr key={i} className={`${styles.tableRow} ${styles.skeletonRow}`}>
          <td><div className={styles.skeletonLine} style={{ width: `${60 + i * 8}%` }} /></td>
          <td><div className={styles.skeletonLine} style={{ width: '60px' }} /></td>
          <td><div className={styles.skeletonLine} style={{ width: '70px' }} /></td>
          <td><div className={styles.skeletonLine} style={{ width: '90px' }} /></td>
          <td><div className={styles.skeletonLine} style={{ width: '50px', marginLeft: 'auto' }} /></td>
        </tr>
      ))}
    </>
  )
}

// ── Report Modal ──────────────────────────────────────────────────────────────

interface ReportModalProps {
  doc: HistoryDocument
  onClose: () => void
}

function ReportModal({ doc, onClose }: ReportModalProps) {
  const [downloading, setDownloading] = useState(false)

  const report   = doc.report
  const score    = report?.global_score ?? 0
  const originality = 100 - score

  async function handleDownload() {
    if (!report?.report_data) return
    setDownloading(true)
    try {
      await generatePdfReport(report.report_data, doc.filename)
    } finally {
      setDownloading(false)
    }
  }

  // Close on backdrop click
  function handleBackdrop(e: React.MouseEvent<HTMLDivElement>) {
    if (e.target === e.currentTarget) onClose()
  }

  // Close on Escape key
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const scoreColor = originality >= 75 ? '#4ade80' : originality >= 50 ? '#FFDC00' : '#f87171'

  return (
    <div className={styles.modalOverlay} onClick={handleBackdrop}>
      <div className={styles.modal}>
        {/* Header */}
        <div className={styles.modalHeader}>
          <div>
            <h2 className={styles.modalTitle}>Report Details</h2>
            <p className={styles.modalFilename}>{doc.filename}</p>
          </div>
          <button className={styles.modalClose} onClick={onClose} aria-label="Close">×</button>
        </div>

        {report ? (
          <>
            {/* Score */}
            <div className={styles.modalScore}>
              <div>
                <div className={styles.modalScoreNum} style={{ color: scoreColor }}>
                  {originality.toFixed(1)}%
                </div>
                <div className={styles.modalScoreLabel}>originality</div>
              </div>
              <div style={{ flex: 1, borderLeft: '1px solid rgba(255,255,255,0.07)', paddingLeft: 20 }}>
                <div style={{ fontSize: 13, color: '#6b7899', marginBottom: 4 }}>Similarity score</div>
                <div style={{ fontSize: 24, fontWeight: 700, color: score > 50 ? '#f87171' : '#e8edff' }}>
                  {score.toFixed(1)}%
                </div>
              </div>
              <div style={{ borderLeft: '1px solid rgba(255,255,255,0.07)', paddingLeft: 20 }}>
                <div style={{ fontSize: 13, color: '#6b7899', marginBottom: 4 }}>Checked</div>
                <div style={{ fontSize: 13, color: '#a8b4d4' }}>
                  {formatDateTime(report.created_at)}
                </div>
              </div>
            </div>

            {/* Meta cards */}
            <div className={styles.modalMeta}>
              {[
                { val: doc.word_count?.toLocaleString() ?? '—', key: 'Words' },
                {
                  val: report.report_data?.document_stats?.total_chunks_analyzed ?? '—',
                  key: 'Chunks',
                },
                {
                  val: report.report_data?.sources?.length ?? '—',
                  key: 'Sources',
                },
              ].map(m => (
                <div key={m.key} className={styles.modalMetaCard}>
                  <div className={styles.modalMetaVal}>{m.val}</div>
                  <div className={styles.modalMetaKey}>{m.key}</div>
                </div>
              ))}
            </div>

            {/* Actions */}
            <div className={styles.modalActions}>
              <button
                className={styles.modalDownloadBtn}
                onClick={handleDownload}
                disabled={downloading}
              >
                {downloading ? (
                  <span className={styles.spinner} />
                ) : (
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
                    stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                    <polyline points="7 10 12 15 17 10"/>
                    <line x1="12" y1="15" x2="12" y2="3"/>
                  </svg>
                )}
                {downloading ? 'Generating report…' : 'Download .docx report'}
              </button>
              <button className={styles.modalCancelBtn} onClick={onClose}>Close</button>
            </div>
          </>
        ) : (
          <p style={{ color: '#6b7899', fontSize: 14 }}>
            No report data available for this document.
          </p>
        )}
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function HistoryPage() {
  const [docs,    setDocs]    = useState<HistoryDocument[]>([])
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState<string | null>(null)
  const [search,  setSearch]  = useState('')
  const [selected, setSelected] = useState<HistoryDocument | null>(null)
  const [downloadingId, setDownloadingId] = useState<number | null>(null)

  // ── Fetch documents ────────────────────────────────────────────────────────
  useEffect(() => {
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const token = localStorage.getItem('access_token')
        const res = await fetch(`${API}/documents/`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        })
        if (!res.ok) {
          const body = await res.json().catch(() => ({}))
          throw new Error((body as { detail?: string }).detail ?? `Server error ${res.status}`)
        }
        const data: HistoryDocument[] = await res.json()
        setDocs(data)
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load history')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  // ── Filter ─────────────────────────────────────────────────────────────────
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return docs
    return docs.filter(d => d.filename.toLowerCase().includes(q))
  }, [docs, search])

  // ── Quick download (without opening modal) ─────────────────────────────────
  async function handleQuickDownload(
    e: React.MouseEvent,
    doc: HistoryDocument,
  ) {
    e.stopPropagation()
    if (!doc.report?.report_data) return
    setDownloadingId(doc.id)
    try {
      await generatePdfReport(doc.report.report_data, doc.filename)
    } finally {
      setDownloadingId(null)
    }
  }

  // ── Stats ──────────────────────────────────────────────────────────────────
  const completedDocs = docs.filter(d => d.status === 'COMPLETED')
  const avgScore      = completedDocs.length
    ? completedDocs.reduce((s, d) => s + (d.report?.global_score ?? 0), 0) / completedDocs.length
    : 0

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className={styles.page}>
      <Navbar />

      <main className={styles.main}>

        {/* ── Header ────────────────────────────────────────────────────────── */}
        <div className={styles.header}>
          <div className={styles.headerTop}>
            <div>
              <h1 className={styles.title}>History</h1>
              <p className={styles.subtitle}>All documents you've submitted for analysis</p>
            </div>

            {/* Search */}
            <label className={styles.searchBar}>
              <span className={styles.searchIcon}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                  stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
                </svg>
              </span>
              <input
                className={styles.searchInput}
                type="text"
                placeholder="Search by filename…"
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
            </label>
          </div>
        </div>

        {/* ── Stats strip ───────────────────────────────────────────────────── */}
        {!loading && !error && (
          <div className={styles.statsStrip}>
            <div className={styles.statPill}>
              <span className={styles.statPillVal}>{docs.length}</span> total submissions
            </div>
            <div className={styles.statPill}>
              <span className={styles.statPillVal}>{completedDocs.length}</span> analysed
            </div>
            {completedDocs.length > 0 && (
              <div className={styles.statPill}>
                avg similarity&nbsp;
                <span className={styles.statPillVal}>{avgScore.toFixed(1)}%</span>
              </div>
            )}
          </div>
        )}

        {/* ── Error ─────────────────────────────────────────────────────────── */}
        {error && <div className={styles.errorBanner}>⚠ {error}</div>}

        {/* ── Table ─────────────────────────────────────────────────────────── */}
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead className={styles.tableHead}>
              <tr>
                <th>Document</th>
                <th>Similarity</th>
                <th>Status</th>
                <th>Submitted</th>
                <th style={{ textAlign: 'right' }}>Action</th>
              </tr>
            </thead>
            <tbody>
              {loading && <SkeletonRows />}

              {!loading && !error && filtered.length === 0 && (
                <tr>
                  <td colSpan={5}>
                    <div className={styles.emptyState}>
                      <div className={styles.emptyIcon}>
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none"
                          stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                          <polyline points="14 2 14 8 20 8"/>
                        </svg>
                      </div>
                      {search ? (
                        <>
                          <p className={styles.emptyTitle}>No results for "{search}"</p>
                          <p className={styles.emptyBody}>Try a different filename.</p>
                        </>
                      ) : (
                        <>
                          <p className={styles.emptyTitle}>No submissions yet</p>
                          <p className={styles.emptyBody}>
                            Upload a document and run an analysis — it will appear here.
                          </p>
                          <Link to="/check" className={styles.emptyLink}>Check a document</Link>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              )}

              {!loading && !error && filtered.map(doc => {
                const score      = doc.report?.global_score ?? null
                const hasReport  = doc.status === 'COMPLETED' && !!doc.report?.report_data
                const isDownloading = downloadingId === doc.id

                return (
                  <tr
                    key={doc.id}
                    className={styles.tableRow}
                    onClick={() => hasReport && setSelected(doc)}
                    title={hasReport ? 'Click to view report details' : undefined}
                    style={{ cursor: hasReport ? 'pointer' : 'default' }}
                  >
                    {/* File */}
                    <td>
                      <div className={styles.fileCell}>
                        <FileIcon />
                        <div>
                          <div className={styles.fileName}>{doc.filename}</div>
                          <div className={styles.fileWords}>
                            {doc.word_count != null
                              ? `${doc.word_count.toLocaleString()} words`
                              : 'words unknown'}
                          </div>
                        </div>
                      </div>
                    </td>

                    {/* Similarity score */}
                    <td>
                      {score !== null ? (
                        <span className={`${styles.scoreBadge} ${scoreClass(score)}`}>
                          <span className={styles.scoreDot} />
                          {score.toFixed(1)}%
                        </span>
                      ) : (
                        <span style={{ color: '#4b5472', fontSize: 13 }}>—</span>
                      )}
                    </td>

                    {/* Status */}
                    <td>
                      <span className={`${styles.statusBadge} ${
                        doc.status === 'COMPLETED' ? styles.statusCompleted :
                        doc.status === 'FAILED'    ? styles.statusFailed    :
                        styles.statusPending
                      }`}>
                        {doc.status === 'COMPLETED' ? '✓ Done'    :
                         doc.status === 'FAILED'    ? '✕ Failed'  :
                         doc.status === 'PROCESSING' ? '⟳ Running' : '· Pending'}
                      </span>
                    </td>

                    {/* Date */}
                    <td>
                      <span className={styles.dateCell}>{formatDate(doc.uploaded_at)}</span>
                    </td>

                    {/* Action */}
                    <td className={styles.actionCell}>
                      {hasReport && (
                        <button
                          className={styles.downloadBtn}
                          onClick={e => handleQuickDownload(e, doc)}
                          disabled={isDownloading}
                          title="Download .docx report"
                        >
                          {isDownloading ? (
                            <span className={styles.spinner} />
                          ) : (
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
                              stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                              <polyline points="7 10 12 15 17 10"/>
                              <line x1="12" y1="15" x2="12" y2="3"/>
                            </svg>
                          )}
                          {isDownloading ? 'Generating…' : 'Download'}
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </main>

      {/* ── Report modal ──────────────────────────────────────────────────────── */}
      {selected && (
        <ReportModal
          doc={selected}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  )
}