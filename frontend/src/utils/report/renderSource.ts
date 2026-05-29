// ── renderSource.ts ───────────────────────────────────────────────────────────

import jsPDF from 'jspdf'
import {
  C, CW, FONT_BODY, FONT_TINY, LINE_H, ML, MR, MT, PH, PW,
  scoreColor,
} from './helpers/constants'
import { pageFooter, pageHeader } from './layout'
import { addPage, currentPage, fillRounded, strokeRounded, wrap } from './primitives'
import type { EngineSource, ReportFilter } from './helpers/types'

function drawSourceHeader(doc: jsPDF, src: EngineSource, index: number, y: number): number {
  const isExact = src.has_exact_copies
  const hCol    = isExact ? C.red    : C.purple
  const hBg     = isExact ? C.redBg  : C.purpleBg
  const H = 22

  fillRounded(doc, ML, y, CW, H, 4, hBg)

  // Circle — smaller radius, bigger number
  const R  = 5
  const CX = ML + 10
  const CY = y + H / 2
  doc.setFillColor(...hCol)
  doc.circle(CX, CY, R, 'F')
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(10)
  doc.setTextColor(...C.white)
  doc.text(String(index + 1), CX, CY + 3.6, { align: 'center' })

  // Detection chip
  fillRounded(doc, ML + 19, y + 6.5, 26, 6, 3, hCol)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(5.5)
  doc.setTextColor(...C.white)
  doc.text(isExact ? 'EXACT COPY' : 'PARAPHRASE', ML + 32, y + 11, { align: 'center' })

  // Title
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(9)
  doc.setTextColor(...C.textMain)
  const titleW = CW - 90
  const titleLines = wrap(doc, src.title || src.arxiv_id, titleW)
  doc.text(titleLines[0], ML + 49, y + 10)

  // arXiv link
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(FONT_TINY)
  doc.setTextColor(...C.textDim)
  doc.text(`arxiv.org/abs/${src.arxiv_id}`, ML + 49, y + 16.5)
  doc.link(ML + 49, y + 13, 70, 5, { url: `https://arxiv.org/abs/${src.arxiv_id}` })

  // Similarity — right
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(16)
  doc.setTextColor(...scoreColor(src.average_similarity_percent))
  doc.text(`${src.average_similarity_percent.toFixed(1)}%`, PW - MR - 3, y + 12, { align: 'right' })

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(FONT_TINY)
  doc.setTextColor(...C.textDim)
  doc.text(`${src.match_count} match${src.match_count !== 1 ? 'es' : ''}`, PW - MR - 3, y + 19, { align: 'right' })

  return y + H + 5
}

function estimateMatchHeight(doc: jsPDF, queryText: string, dbText: string | undefined, phrases: string[]): number {
  const yourLines = wrap(doc, queryText || '', CW - 12)
  const dbLines   = dbText ? wrap(doc, dbText, CW - 14) : []
  const phLines   = phrases.flatMap(ph => wrap(doc, `"${ph}"`, CW - 14))
  return (
    10 + 5
    + 3 + yourLines.length * LINE_H + 10 + 5
    + (dbLines.length ? 3 + dbLines.length * LINE_H + 10 + 5 : 0)
    + (phLines.length ? 3 + phLines.length * 4 + 5 : 0)
    + 8
  )
}

export function renderSource(
  doc:          jsPDF,
  src:          EngineSource,
  srcIndex:     number,
  totalPages:   number,
  fileName:     string,
  submissionId: string,
  date:         string,
  filter:       ReportFilter,
) {
  const pg = currentPage(doc)
  pageHeader(doc, fileName, pg, totalPages)
  pageFooter(doc, submissionId, date)

  const filteredMatches = src.matches.filter(m => {
    if (filter === 'exact')      return m.detection !== 'paraphrase'
    if (filter === 'paraphrase') return m.detection === 'paraphrase'
    return true
  })

  let y = MT + 6
  y = drawSourceHeader(doc, src, srcIndex, y)

  if (filteredMatches.length === 0) {
    doc.setFont('helvetica', 'italic')
    doc.setFontSize(FONT_BODY)
    doc.setTextColor(...C.textMuted)
    doc.text(`No ${filter} matches for this source.`, ML, y)
    return
  }

  filteredMatches.forEach((m, mi) => {
    const isParaphrase = m.detection === 'paraphrase'
    const mCol    = isParaphrase ? C.purple   : C.red
    const mBg     = isParaphrase ? C.purpleBg : C.redBg
    const phrases = m.exact_copied_phrases ?? []
    const yourLines = wrap(doc, m.query_text || '', CW - 12)
    const dbLines   = m.db_text ? wrap(doc, m.db_text, CW - 14) : []
    const estH = estimateMatchHeight(doc, m.query_text, m.db_text, phrases)

    if (y + estH > PH - 16) {
      addPage(doc)
      const newPg = currentPage(doc)
      pageHeader(doc, fileName, newPg, totalPages)
      pageFooter(doc, submissionId, date)
      y = MT + 6
    }

    // ── Match header pill ─────────────────────────────────────────────────
    fillRounded(doc, ML, y, CW, 9, 4, C.cardBg)
    strokeRounded(doc, ML, y, CW, 9, 4, C.border, 0.2)

    // Small dot — vertically centered in the 9mm pill
    doc.setFillColor(...mCol)
    doc.circle(ML + 6, y + 4.5, 1.8, 'F')

    doc.setFont('helvetica', 'bold')
    doc.setFontSize(6.5)
    doc.setTextColor(...C.textMain)
    doc.text(`${mi + 1}.  ${isParaphrase ? 'Paraphrase' : 'Exact match'}`, ML + 11, y + 5.8)

    doc.setFont('helvetica', 'normal')
    doc.setFontSize(FONT_TINY)
    doc.setTextColor(...C.textDim)
    doc.text(`${m.match_percentage.toFixed(1)}% similarity`, PW - MR - 3, y + 5.8, { align: 'right' })

    y += 13

    // ── YOUR TEXT ─────────────────────────────────────────────────────────
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(5.5)
    doc.setTextColor(...C.textDim)
    doc.text('YOUR TEXT', ML + 1, y)
    y += 2.5

    const yourH = yourLines.length * LINE_H + 10
    fillRounded(doc, ML, y, CW, yourH, 3, C.cardBg)
    strokeRounded(doc, ML, y, CW, yourH, 3, C.border, 0.2)
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(FONT_BODY)
    doc.setTextColor(...C.textMain)
    yourLines.forEach((line, li) => doc.text(line, ML + 5, y + 5.5 + li * LINE_H))
    y += yourH + 5

    // ── MATCHED SOURCE ────────────────────────────────────────────────────
    if (dbLines.length) {
      doc.setFont('helvetica', 'bold')
      doc.setFontSize(5.5)
      doc.setTextColor(...C.textDim)
      doc.text('MATCHED SOURCE', ML + 1, y)
      y += 2.5

      const dbH = dbLines.length * LINE_H + 10

      // Soft tinted card — no border stroke
      fillRounded(doc, ML, y, CW, dbH, 3, mBg)

      // Left accent bar — offset 1mm from left edge so rounded corners show
      doc.setFillColor(...mCol)
      doc.roundedRect(ML + 0.8, y + 2, 2.5, dbH - 4, 1, 1, 'F')

      doc.setFont('helvetica', 'normal')
      doc.setFontSize(FONT_BODY)
      doc.setTextColor(...C.textMain)
      // Text starts after the accent bar with padding
      dbLines.forEach((line, li) => doc.text(line, ML + 6, y + 5.5 + li * LINE_H))
      y += dbH + 5
    }

    // ── EXACT PHRASES ─────────────────────────────────────────────────────
    if (phrases.length) {
      const phLines = phrases.flatMap(ph => wrap(doc, `"${ph}"`, CW - 14))

      doc.setFont('helvetica', 'bold')
      doc.setFontSize(5.5)
      doc.setTextColor(...C.red)
      doc.text('EXACT PHRASES', ML + 1, y)
      y += 2.5

      doc.setFont('helvetica', 'italic')
      doc.setFontSize(7.5)
      doc.setTextColor(...C.red)
      phLines.forEach(line => { doc.text(line, ML + 3, y); y += 4 })
      y += 3
    }

    // Separator
    y += 2
    doc.setDrawColor(...C.border)
    doc.setLineWidth(0.2)
    doc.line(ML, y, PW - MR, y)
    y += 8
  })
}