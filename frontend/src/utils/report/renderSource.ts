// ── renderSource.ts ───────────────────────────────────────────────────────────

import jsPDF from 'jspdf'
import {
  C, CW, FONT_BODY, FONT_TINY, FONT_SMALL, LINE_H,
  ML, MR, MT, PH, PW,
  scoreColor,
} from './helpers/constants'
import { pageFooter, pageHeader } from './layout'
import { addPage, currentPage, fillRounded, strokeRounded, wrap } from './primitives'
import type { EngineSource, ReportFilter } from './helpers/types'

// ── Source header ─────────────────────────────────────────────────────────────

function drawSourceHeader(doc: jsPDF, src: EngineSource, index: number, y: number): number {
  const isExact = src.has_exact_copies
  const hCol    = isExact ? C.red    : C.purple
  const hBg     = isExact ? C.redBg  : C.purpleBg
  const H       = 20

  fillRounded(doc, ML, y, CW, H, 4, hBg)
  strokeRounded(doc, ML, y, CW, H, 4, hCol, 0.3)

  // Index circle
  doc.setFillColor(...hCol)
  doc.circle(ML + 9, y + H / 2, 5, 'F')
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(8)
  doc.setTextColor(...C.white)
  doc.text(String(index + 1), ML + 9, y + H / 2 + 3, { align: 'center' })

  // Type chip
  fillRounded(doc, ML + 18, y + 6, 24, 7, 2, hCol)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(5)
  doc.setTextColor(...C.white)
  doc.text(isExact ? 'EXACT COPY' : 'PARAPHRASE', ML + 30, y + 11, { align: 'center' })

  // Title
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(FONT_SMALL)
  doc.setTextColor(...C.textMain)
  const titleW = CW - 90
  const titleLines = wrap(doc, src.title || src.arxiv_id, titleW)
  doc.text(titleLines[0], ML + 46, y + 9)

  // arXiv link
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(FONT_TINY)
  doc.setTextColor(...C.textDim)
  doc.text(`arxiv.org/abs/${src.arxiv_id}`, ML + 46, y + 15)
  doc.link(ML + 46, y + 12, 65, 4, { url: `https://arxiv.org/abs/${src.arxiv_id}` })

  // Similarity — right
  const contrib = src.score_contribution_percent ?? src.average_similarity_percent
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(14)
  doc.setTextColor(...scoreColor(contrib))
  doc.text(`${contrib.toFixed(1)}%`, PW - MR - 2, y + 11, { align: 'right' })

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(FONT_TINY)
  doc.setTextColor(...C.textDim)
  doc.text(`${src.match_count} match${src.match_count !== 1 ? 'es' : ''}`, PW - MR - 2, y + 17, { align: 'right' })

  return y + H + 6
}

// ── Match card — side-by-side diff layout ─────────────────────────────────────

function drawMatchCard(
  doc:       jsPDF,
  m:         { query_text: string; db_text?: string; match_percentage: number; detection?: string; exact_copied_phrases?: string[] },
  index:     number,
): number {
  const phrases = m.exact_copied_phrases ?? []

  // Column widths for side-by-side layout
  const COL_GAP = 3
  const COL_W   = (CW - COL_GAP) / 2

  // Pre-wrap text in each column
  const yourLines = wrap(doc, m.query_text || '', COL_W - 8)
  const dbLines   = m.db_text ? wrap(doc, m.db_text, COL_W - 8) : []
  const maxLines  = Math.max(yourLines.length, dbLines.length, 1)
  const textH     = maxLines * LINE_H + 10

  // Phrases row height
  const phLines = phrases.flatMap(ph => wrap(doc, `"${ph}"`, COL_W - 4))
  const phH     = phLines.length > 0 ? phLines.length * 4.2 + 10 : 0

  // Total card height: header pill + columns + optional phrases
  const CARD_H = 9 + 4 + textH + (phH > 0 ? phH + 3 : 0) + 4

  return CARD_H
}

function renderMatchCard(
  doc:       jsPDF,
  m:         { query_text: string; db_text?: string; match_percentage: number; detection?: string; exact_copied_phrases?: string[] },
  index:     number,
  y:         number,
): number {
  const isParaphrase = m.detection === 'paraphrase'
  const mCol   = isParaphrase ? C.purple   : C.red
  const mBg    = isParaphrase ? C.purpleBg : C.redBg
  const phrases = m.exact_copied_phrases ?? []

  const COL_GAP = 3
  const COL_W   = (CW - COL_GAP) / 2

  const yourLines = wrap(doc, m.query_text || '', COL_W - 8)
  const dbLines   = m.db_text ? wrap(doc, m.db_text, COL_W - 8) : []
  const maxLines  = Math.max(yourLines.length, dbLines.length, 1)
  const textH     = maxLines * LINE_H + 10
  const phLines   = phrases.flatMap(ph => wrap(doc, `"${ph}"`, CW - 8))
  const phH       = phLines.length > 0 ? phLines.length * 4.2 + 10 : 0
  const CARD_H    = 9 + 4 + textH + (phH > 0 ? phH + 3 : 0) + 4

  // ── Card border ───────────────────────────────────────────────────────────
  strokeRounded(doc, ML, y, CW, CARD_H, 3, C.border, 0.2)

  // ── Header row ────────────────────────────────────────────────────────────
  fillRounded(doc, ML, y, CW, 9, 3, C.cardBg)

  // Index + type badge
  doc.setFillColor(...mCol)
  doc.circle(ML + 5, y + 4.5, 1.5, 'F')
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(6)
  doc.setTextColor(...C.textMuted)
  doc.text(`${index + 1}.`, ML + 9, y + 6)

  fillRounded(doc, ML + 14, y + 1.5, 22, 6, 2, mBg)
  strokeRounded(doc, ML + 14, y + 1.5, 22, 6, 2, mCol, 0.3)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(5)
  doc.setTextColor(...mCol)
  doc.text(isParaphrase ? 'Paraphrase' : 'Exact copy', ML + 25, y + 5.8, { align: 'center' })

  // Similarity pill — right
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(6)
  doc.setTextColor(...C.textMuted)
  doc.text(`${m.match_percentage.toFixed(1)}% similarity`, PW - MR, y + 6, { align: 'right' })

  // Divider under header
  doc.setDrawColor(...C.border)
  doc.setLineWidth(0.15)
  doc.line(ML, y + 9, PW - MR, y + 9)

  let contentY = y + 9 + 4

  // ── Column labels ─────────────────────────────────────────────────────────
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(5)
  doc.setTextColor(...C.textDim)
  doc.text('YOUR TEXT', ML + 2, contentY)
  if (dbLines.length > 0)
    doc.text('MATCHED SOURCE', ML + COL_W + COL_GAP + 2, contentY)
  contentY += 3

  // ── Left column: your text ────────────────────────────────────────────────
  fillRounded(doc, ML, contentY, COL_W, textH, 2, C.cardBg)
  strokeRounded(doc, ML, contentY, COL_W, textH, 2, C.border, 0.15)

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(FONT_BODY)
  doc.setTextColor(...C.textMain)
  yourLines.forEach((line, li) =>
    doc.text(line, ML + 4, contentY + 5.5 + li * LINE_H)
  )

  // ── Right column: matched source ──────────────────────────────────────────
  if (dbLines.length > 0) {
    const rx = ML + COL_W + COL_GAP
    fillRounded(doc, rx, contentY, COL_W, textH, 2, mBg)
    strokeRounded(doc, rx, contentY, COL_W, textH, 2, mCol, 0.2)

    doc.setFont('helvetica', 'normal')
    doc.setFontSize(FONT_BODY)
    doc.setTextColor(...C.textMain)
    dbLines.forEach((line, li) =>
      doc.text(line, rx + 4, contentY + 5.5 + li * LINE_H)
    )
  }

  contentY += textH + 3

  // ── Exact phrases row ─────────────────────────────────────────────────────
  if (phLines.length > 0) {
    doc.setDrawColor(...C.border)
    doc.setLineWidth(0.15)
    doc.line(ML, contentY, PW - MR, contentY)
    contentY += 3

    doc.setFont('helvetica', 'bold')
    doc.setFontSize(5)
    doc.setTextColor(...C.red)
    doc.text('EXACT PHRASES', ML + 2, contentY)
    contentY += 3.5

    doc.setFont('helvetica', 'italic')
    doc.setFontSize(6.5)
    doc.setTextColor(...C.red)
    phLines.forEach(line => {
      doc.text(line, ML + 3, contentY)
      contentY += 4.2
    })
  }

  return y + CARD_H + 5
}

// ── Main source renderer ──────────────────────────────────────────────────────

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
    const estH = drawMatchCard(doc, m, mi)

    if (y + estH > PH - 16) {
      addPage(doc)
      const newPg = currentPage(doc)
      pageHeader(doc, fileName, newPg, totalPages)
      pageFooter(doc, submissionId, date)
      y = MT + 6
    }

    y = renderMatchCard(doc, m, mi, y)
  })
}