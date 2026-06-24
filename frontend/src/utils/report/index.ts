import jsPDF from 'jspdf'
import { C, PH, PW } from './helpers/constants'
import { fillRect } from './primitives'
import { renderCover } from './renderCover'
import { renderDocumentView } from '../report/renderDocument.ts'
import { renderSource } from './renderSource'
import type { EngineReport, ReportFilter } from './helpers/types'

export type { EngineMatch, EngineReport, EngineSource, ReportFilter } from './helpers/types'

// ── Safe-data normalisation ───────────────────────────────────────────────────
function safeReport(data: EngineReport): EngineReport {
  return {
    ...data,
    global_plagiarism_score_percent: data.global_plagiarism_score_percent ?? 0,
    total_reported_sources:          data.total_reported_sources           ?? 0,
    total_suspicious_sources:        data.total_suspicious_sources         ?? 0,
    document_stats: {
      total_words:           data.document_stats?.total_words           ?? 0,
      total_chunks_analyzed: data.document_stats?.total_chunks_analyzed ?? 0,
    },
    sources: data.sources ?? [],
  }
}

// ── Main export ───────────────────────────────────────────────────────────────
export async function generatePdfReport(
  data:             EngineReport,
  originalFileName: string,
  filter:           ReportFilter = 'all',
): Promise<void> {
  const report       = safeReport(data)
  const fileName     = report.file_name ?? originalFileName
  const submissionId = `sentinel:${Date.now()}`
  const date         = new Date().toLocaleString('en-GB')

  const flaggedChunks = new Set(
    report.sources.flatMap(s => s.matches.map(m => m.query_chunk_idx))
  ).size
  const docViewPages = Math.max(1, Math.ceil(flaggedChunks / 10))
  const totalPages   = 1 + report.sources.length + docViewPages

  const doc = new jsPDF({ unit: 'mm', format: 'a4', compress: true })
  fillRect(doc, 0, 0, PW, PH, C.pageBg)

  // ── Page 1: Cover ───────────────────────────────────────────────────────
  renderCover(doc, report, submissionId, date, filter, totalPages)

  // ── Pages 2…N+1: Per-source detail ────────────────────────────────────
  report.sources.forEach((src, i) => {
    doc.addPage()
    fillRect(doc, 0, 0, PW, PH, C.pageBg)
    renderSource(doc, src, i, totalPages, fileName, submissionId, date, filter)
  })

  // ── Pages N+2…end: Annotated document view ─────────────────────────────
  renderDocumentView(doc, report, totalPages, fileName, submissionId, date, filter)

  // ── Save ───────────────────────────────────────────────────────────────
  const baseName = fileName.replace(/\.[^/.]+$/, '')
  const suffix   = filter !== 'all' ? `_${filter}` : ''
  doc.save(`plagiarism_report_${baseName}${suffix}.pdf`)
}