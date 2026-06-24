import jsPDF from 'jspdf'
import {
  C, CW, FONT_BODY, FONT_TINY, FONT_SMALL,
  ML, MR, MT, PH, PW,
  scoreColor, scoreBgColor, scoreMutedColor,
} from './helpers/constants'
import { pageFooter, pageHeader } from './layout'
import { fillRounded, strokeRounded, wrap } from './primitives'
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

  let y = MT + 10

  // ── Document name + meta ───────────────────────────────────────────────────
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(14)
  doc.setTextColor(...C.textMain)
  const nameLines = wrap(doc, fileName, CW)
  doc.text(nameLines[0], ML, y)
  y += 6

  const filterLabel =
    filter === 'exact'      ? 'Exact matches only'
    : filter === 'paraphrase' ? 'Paraphrases only'
    : 'All matches'

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(FONT_SMALL)
  doc.setTextColor(...C.textMuted)
  doc.text(`${date}  ·  ${filterLabel}`, ML, y)
  y += 12

  // ── Hero row: ring left, stat strip right ──────────────────────────────────
  const sim    = data.global_plagiarism_score_percent
  const sCol   = scoreColor(sim)
  const sBg    = scoreBgColor(sim)
  const sMuted = scoreMutedColor(sim)

  // Ring — mimics the app's SVG ring
  const R   = 18
  const CX  = ML + R + 2
  const CY  = y + R + 2

  // Track circle (light bg)
  doc.setFillColor(...sBg)
  doc.circle(CX, CY, R, 'F')
  doc.setDrawColor(...sMuted)
  doc.setLineWidth(0.5)
  doc.circle(CX, CY, R, 'S')

  const arcPct  = Math.min(sim / 100, 1)
  const arcStart = -Math.PI / 2
  const arcEnd   = arcStart + arcPct * 2 * Math.PI
  const SEGS     = 60
  const THICK    = 3.5
  doc.setDrawColor(...sCol)
  doc.setLineWidth(THICK)
  for (let s = 0; s < SEGS; s++) {
    const a1 = arcStart + (s / SEGS) * (arcEnd - arcStart)
    const a2 = arcStart + ((s + 1) / SEGS) * (arcEnd - arcStart)
    doc.line(
      CX + R * Math.cos(a1),
      CY + R * Math.sin(a1),
      CX + R * Math.cos(a2),
      CY + R * Math.sin(a2),
    )
  }
  doc.setLineWidth(0.25)

  // Score number centered in ring
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(13)
  doc.setTextColor(...sCol)
  doc.text(`${sim.toFixed(1)}%`, CX, CY + 2, { align: 'center' })

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(4.5)
  doc.setTextColor(...sMuted)
  doc.text('SIMILARITY', CX, CY + 7, { align: 'center' })

  // Stat strip — 3 cells to the right of the ring, bordered like the app
  const STRIP_X = CX + R + 10
  const STRIP_W = PW - MR - STRIP_X
  const STRIP_H = (R + 2) * 2
  const CELL_W  = STRIP_W / 3

  const stats = [
    { val: String(data.total_reported_sources ?? data.sources?.length ?? 0), lbl: 'Sources' },
    { val: String(data.document_stats?.total_chunks_analyzed ?? 0),          lbl: 'Chunks'  },
    { val: (data.document_stats?.total_words ?? 0).toLocaleString(),         lbl: 'Words'   },
  ]

  // Strip border
  strokeRounded(doc, STRIP_X, y, STRIP_W, STRIP_H, 4, C.border, 0.3)

  stats.forEach((s, i) => {
    const cx = STRIP_X + i * CELL_W + CELL_W / 2

    // Vertical divider between cells
    if (i > 0) {
      doc.setDrawColor(...C.border)
      doc.setLineWidth(0.25)
      doc.line(STRIP_X + i * CELL_W, y + 5, STRIP_X + i * CELL_W, y + STRIP_H - 5)
    }

    doc.setFont('helvetica', 'bold')
    doc.setFontSize(16)
    doc.setTextColor(...C.textMain)
    doc.text(s.val, cx, y + STRIP_H / 2 + 1, { align: 'center' })

    doc.setFont('helvetica', 'normal')
    doc.setFontSize(5)
    doc.setTextColor(...C.textDim)
    doc.text(s.lbl.toUpperCase(), cx, y + STRIP_H / 2 + 7, { align: 'center' })
  })

  y = CY + R + 12

  // ── Thin divider ───────────────────────────────────────────────────────────
  doc.setDrawColor(...C.border)
  doc.setLineWidth(0.25)
  doc.line(ML, y, PW - MR, y)
  y += 8

  // ── No sources ─────────────────────────────────────────────────────────────
  if ((data.sources?.length ?? 0) === 0) {
    fillRounded(doc, ML, y, CW, 14, 3, C.greenBg)
    strokeRounded(doc, ML, y, CW, 14, 3, C.green, 0.3)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(FONT_BODY)
    doc.setTextColor(...C.green)
    doc.text('No plagiarism detected — your document appears to be original.', ML + 8, y + 9)
    return
  }

  // ── Matched sources table ──────────────────────────────────────────────────
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(FONT_TINY)
  doc.setTextColor(...C.textMuted)
  doc.text('MATCHED SOURCES', ML, y)
  y += 5

  // Table header row
  fillRounded(doc, ML, y, CW, 7, 2, C.cardBg)
  strokeRounded(doc, ML, y, CW, 7, 2, C.border, 0.2)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(FONT_TINY)
  doc.setTextColor(...C.textDim)
  doc.text('TYPE',    ML + 3,        y + 5)
  doc.text('SOURCE',  ML + 26,       y + 5)
  doc.text('MATCHES', PW - MR - 26,  y + 5, { align: 'right' })
  doc.text('COVERAGE',PW - MR,       y + 5, { align: 'right' })
  y += 9

  data.sources.forEach((src, i) => {
    if (y > PH - 16) return

    const ROW_H = 14
    const isLast = i === data.sources.length - 1

    // Row background
    if (i % 2 === 1) fillRounded(doc, ML, y, CW, ROW_H, 0, C.cardBg)

    // Bottom divider
    if (!isLast) {
      doc.setDrawColor(...C.border)
      doc.setLineWidth(0.15)
      doc.line(ML, y + ROW_H, PW - MR, y + ROW_H)
    } else {
      doc.setDrawColor(...C.border)
      doc.setLineWidth(0.15)
      doc.line(ML, y + ROW_H, PW - MR, y + ROW_H)
    }

    // Left + right border for the table body
    doc.setDrawColor(...C.border)
    doc.setLineWidth(0.15)
    if (i === 0) doc.line(ML, y, PW - MR, y) // top of first row

    // Detection badge
    const isExact  = src.has_exact_copies
    const badgeCol = isExact ? C.red    : C.purple
    const badgeBg  = isExact ? C.redBg  : C.purpleBg
    const badgeTxt = isExact ? '● EXACT' : '● PARA.'

    fillRounded(doc, ML + 2, y + 3.5, 20, 6, 2, badgeBg)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(5)
    doc.setTextColor(...badgeCol)
    doc.text(badgeTxt, ML + 12, y + 7.5, { align: 'center' })

    // Source title
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(FONT_SMALL)
    doc.setTextColor(...C.textMain)
    const titleMaxW = CW - 70
    const titleLines = wrap(doc, `${i + 1}.  ${src.title || src.arxiv_id}`, titleMaxW)
    doc.text(titleLines[0], ML + 26, y + 6.5)

    // arXiv link
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(FONT_TINY)
    doc.setTextColor(...C.textDim)
    doc.text(`arxiv.org/abs/${src.arxiv_id}`, ML + 26, y + 11)
    doc.link(ML + 26, y + 8, 55, 4, { url: `https://arxiv.org/abs/${src.arxiv_id}` })

    // Match count
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(FONT_SMALL)
    doc.setTextColor(...C.textMuted)
    doc.text(String(src.match_count), PW - MR - 26, y + 8, { align: 'right' })

    // Coverage %
    const contrib = src.score_contribution_percent ?? src.average_similarity_percent
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(FONT_SMALL)
    doc.setTextColor(...scoreColor(contrib))
    doc.text(`${contrib.toFixed(1)}%`, PW - MR, y + 8, { align: 'right' })

    y += ROW_H
  })
}