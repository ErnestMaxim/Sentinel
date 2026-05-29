// ── renderCover.ts ────────────────────────────────────────────────────────────

import jsPDF from 'jspdf'
import {
  C, CW, FONT_BODY, FONT_TINY, FONT_SMALL, FONT_SUB, FONT_TITLE,
  ML, MR, MT, PH, PW,
  scoreColor, scoreBgColor, scoreMutedColor,
} from './helpers/constants'
import { pageFooter, pageHeader } from './layout'
import { fillRect, fillRounded, strokeRounded, wrap } from './primitives'
import type { EngineReport, ReportFilter } from './helpers/types'

export function renderCover(
  doc:          jsPDF,
  data:         EngineReport,
  submissionId: string,
  date:         string,
  filter:       ReportFilter,
  totalPages:   number,
) {
  const fileName = data.file_name ?? 'Document'
  pageHeader(doc, fileName, 1, totalPages)
  pageFooter(doc, submissionId, date)

  let y = MT + 14

  // ── Document name ──────────────────────────────────────────────────────────
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(FONT_TITLE)
  doc.setTextColor(...C.textMain)
  const nameLines = wrap(doc, fileName, CW)
  doc.text(nameLines[0], ML, y)
  y += 7

  const filterLabel =
    filter === 'exact'       ? 'Exact matches only'
    : filter === 'paraphrase'  ? 'Paraphrases only'
    : 'All matches'

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(FONT_SMALL)
  doc.setTextColor(...C.textMuted)
  doc.text(`${date}  ·  ${filterLabel}`, ML, y)
  y += 16

  // ── Score + stats layout ───────────────────────────────────────────────────
  const sim    = data.global_plagiarism_score_percent
  const sCol   = scoreColor(sim)
  const sBg    = scoreBgColor(sim)
  const sMuted = scoreMutedColor(sim)

  // Circle geometry
  const R  = 22
  const CX = ML + R
  const CY = y + R

  // Outer soft ring
  doc.setFillColor(...sBg)
  doc.circle(CX, CY, R, 'F')
  doc.setDrawColor(...sMuted)
  doc.setLineWidth(1.0)
  doc.circle(CX, CY, R, 'S')

  // Score text
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(17)
  doc.setTextColor(...sCol)
  doc.text(`${sim.toFixed(1)}%`, CX, CY + 1.5, { align: 'center' })

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(5.5)
  doc.setTextColor(...sCol)
  doc.text('SIMILARITY', CX, CY + 7.5, { align: 'center' })

  // Stat pills — stacked to the right of the circle
  const stats = [
    { val: String(data.total_reported_sources ?? data.sources?.length ?? 0), label: 'sources matched' },
    { val: String(data.document_stats?.total_chunks_analyzed ?? 0),          label: 'chunks analyzed' },
    { val: (data.document_stats?.total_words ?? 0).toLocaleString(),         label: 'words' },
  ]

  const PILL_W   = 50
  const PILL_H   = 13
  const PILL_GAP = 4
  const PILLS_X  = CX + R + 10
  // Vertically center the pill stack against the circle
  const totalPillH = stats.length * PILL_H + (stats.length - 1) * PILL_GAP
  const PILLS_Y  = CY - totalPillH / 2

  stats.forEach((s, i) => {
    const px = PILLS_X
    const py = PILLS_Y + i * (PILL_H + PILL_GAP)

    fillRounded(doc, px, py, PILL_W, PILL_H, 3, C.cardBg)
    strokeRounded(doc, px, py, PILL_W, PILL_H, 3, C.border)

    doc.setFont('helvetica', 'bold')
    doc.setFontSize(9.5)
    doc.setTextColor(...C.textMain)
    doc.text(s.val, px + PILL_W / 2, py + 5.5, { align: 'center' })

    doc.setFont('helvetica', 'normal')
    doc.setFontSize(5.2)
    doc.setTextColor(...C.textDim)
    doc.text(s.label.toUpperCase(), px + PILL_W / 2, py + 10.5, { align: 'center' })
  })

  y = CY + R + 14

  // ── Thin divider ───────────────────────────────────────────────────────────
  doc.setDrawColor(...C.border)
  doc.setLineWidth(0.25)
  doc.line(ML, y, PW - MR, y)
  y += 10

  // ── No sources ─────────────────────────────────────────────────────────────
  if ((data.sources?.length ?? 0) === 0) {
    fillRounded(doc, ML, y, CW, 18, 4, C.greenBg)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(FONT_BODY)
    doc.setTextColor(...C.green)
    doc.text('No plagiarism detected — your document appears to be original.', ML + 8, y + 11)
    return
  }

  // ── Matched sources table ──────────────────────────────────────────────────
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(FONT_TINY)
  doc.setTextColor(...C.textMuted)
  doc.text('MATCHED SOURCES', ML, y)
  y += 5

  // Column headers
  fillRounded(doc, ML, y, CW, 7, 2, C.cardBg)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(FONT_TINY)
  doc.setTextColor(...C.textDim)
  doc.text('TYPE',    ML + 3,         y + 5)
  doc.text('SOURCE',  ML + 26,        y + 5)
  doc.text('MATCHES', PW - MR - 38,   y + 5, { align: 'right' })
  doc.text('SIM %',   PW - MR,        y + 5, { align: 'right' })
  y += 9

  data.sources.forEach((src, i) => {
    if (y > PH - 20) return

    const ROW_H  = 15
    const isLast = i === data.sources.length - 1

    // Alternating row bg
    if (i % 2 === 1) fillRounded(doc, ML, y, CW, ROW_H, 0, C.cardBg)

    // Row bottom divider (not after last)
    if (!isLast) {
      doc.setDrawColor(...C.border)
      doc.setLineWidth(0.2)
      doc.line(ML, y + ROW_H, PW - MR, y + ROW_H)
    }

    // Detection badge pill
    const isExact  = src.has_exact_copies
    const badgeCol = isExact ? C.red    : C.purple
    const badgeBg  = isExact ? C.redBg  : C.purpleBg
    fillRounded(doc, ML + 2, y + 4.5, 20, 6, 3, badgeBg)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(5.5)
    doc.setTextColor(...badgeCol)
    doc.text(isExact ? 'EXACT' : 'PARA.', ML + 12, y + 8.7, { align: 'center' })

    // Title
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(FONT_BODY)
    doc.setTextColor(...C.textMain)
    const titleLines = wrap(doc, `${i + 1}.  ${src.title || src.arxiv_id}`, CW - 64)
    doc.text(titleLines[0], ML + 26, y + 7)

    // arXiv link
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(FONT_TINY)
    doc.setTextColor(...C.textDim)
    doc.text(`arxiv.org/abs/${src.arxiv_id}`, ML + 26, y + 12)
    doc.link(ML + 26, y + 8, 65, 4, { url: `https://arxiv.org/abs/${src.arxiv_id}` })

    // Match count
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(FONT_BODY)
    doc.setTextColor(...C.textMuted)
    doc.text(`${src.match_count}`, PW - MR - 38, y + 8, { align: 'right' })

    // Similarity %
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(FONT_SUB)
    doc.setTextColor(...scoreColor(src.average_similarity_percent))
    doc.text(`${src.average_similarity_percent.toFixed(1)}%`, PW - MR, y + 8.5, { align: 'right' })

    y += ROW_H
  })
}