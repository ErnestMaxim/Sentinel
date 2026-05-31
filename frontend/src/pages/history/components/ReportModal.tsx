import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import type { HistoryDocument } from '../../../types/documents'
import { generatePdfReport } from '../../../utils/report'
import { formatDateTime } from '../../../utils/format'
import styles from '../HistoryPage.module.css'
import { REPORT_STORAGE_KEY, type StoredReport } from '../../report/ReportPage'

interface Props {
  doc:     HistoryDocument
  onClose: () => void
}

export default function ReportModal({ doc, onClose }: Props) {
  const navigate    = useNavigate()
  const [downloading, setDownloading] = useState(false)
  const report      = doc.report
  const score       = report?.global_score ?? 0
  const originality = 100 - score

  async function handleDownload() {
    if (!report?.report_data) return
    setDownloading(true)
    try { await generatePdfReport(report.report_data, doc.filename) }
    finally { setDownloading(false) }
  }

  function handleViewReport() {
    if (!report?.report_data) return
    const stored: StoredReport = {
      report:     report.report_data,
      filename:   doc.filename,
      date:       formatDateTime(report.created_at),
      documentId: doc.id,
    }
    sessionStorage.setItem(REPORT_STORAGE_KEY, JSON.stringify(stored))
    navigate('/report')
  }

  function handleBackdrop(e: React.MouseEvent<HTMLDivElement>) {
    if (e.target === e.currentTarget) onClose()
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const origColor = originality >= 75 ? '#4ade80' : originality >= 50 ? '#FFDC00' : '#f87171'
  const simColor  = score > 50 ? '#f87171' : '#e8edff'

  return (
    <div className={styles.modalOverlay} onClick={handleBackdrop}>
      <div className={styles.modal}>
        <div className={styles.modalHeader}>
          <div>
            <h2 className={styles.modalTitle}>Report Details</h2>
            <p className={styles.modalFilename}>{doc.filename}</p>
          </div>
          <button className={styles.modalClose} onClick={onClose} aria-label="Close">×</button>
        </div>

        {report ? (
          <>
            <div className={styles.modalScoreSection}>
              <div className={styles.modalScoreRow}>
                <div className={styles.modalScoreBlock}>
                  <div className={styles.modalScoreNum} style={{ color: origColor }}>
                    {originality.toFixed(1)}%
                  </div>
                  <div className={styles.modalScoreLabel}>originality</div>
                </div>
                <div className={styles.modalScoreDivider} />
                <div className={styles.modalScoreSub}>
                  <div className={styles.modalScoreSubVal} style={{ color: simColor }}>
                    {score.toFixed(1)}%
                  </div>
                  <div className={styles.modalScoreSubLabel}>similarity</div>
                </div>
              </div>
              <div className={styles.modalCheckedAt}>
                Checked {formatDateTime(report.created_at)}
              </div>
            </div>

            <div className={styles.modalMetaGrid}>
              {[
                { val: doc.word_count?.toLocaleString() ?? '—',                          key: 'Words'  },
                { val: report.report_data?.document_stats?.total_chunks_analyzed ?? '—', key: 'Chunks' },
                { val: report.report_data?.sources?.length ?? '—',                       key: 'Sources'},
              ].map(m => (
                <div key={m.key} className={styles.modalMetaItem}>
                  <div className={styles.modalMetaVal}>{m.val}</div>
                  <div className={styles.modalMetaKey}>{m.key}</div>
                </div>
              ))}
            </div>

            <div className={styles.modalActions}>
              {report?.report_data && (
                <button className={styles.modalViewBtn} onClick={handleViewReport}>
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                  View report
                </button>
              )}
              <button className={styles.modalDownloadBtn} onClick={handleDownload} disabled={downloading}>
                {downloading ? <span className={styles.spinner} /> : (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                    stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                    <polyline points="7 10 12 15 17 10"/>
                    <line x1="12" y1="15" x2="12" y2="3"/>
                  </svg>
                )}
                {downloading ? 'Generating…' : 'Download PDF report'}
              </button>
              <button className={styles.modalCancelBtn} onClick={onClose}>Close</button>
            </div>
          </>
        ) : (
          <p style={{ color: '#2e3450', fontSize: 13 }}>No report data available.</p>
        )}
      </div>
    </div>
  )
}
