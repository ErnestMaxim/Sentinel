// ── renderDocument.ts ─────────────────────────────────────────────────────────
// Renders the "Document View" pages.
// Full text flows as continuous paragraphs. Flagged spans get an inline
// highlight — a colored rectangle drawn behind each word in the flagged range,
// like a highlighter pen. No boxes, no cards.

import jsPDF from 'jspdf'
import {
  C, CW, FONT_BODY, FONT_TINY, FONT_SMALL, FONT_HEAD,
  LINE_H, ML, MR, MT, PH, PW,
} from './helpers/constants'
import { pageFooter, pageHeader } from './layout'
import { addPage, currentPage, wrap } from './primitives'
import type { EngineReport, ReportFilter } from './helpers/types'

// ── Types ─────────────────────────────────────────────────────────────────────

interface Span {
  start:     number   // char offset in full_text
  end:       number
  sourceIdx: number
  isExact:   boolean
}

// ── Build flagged spans from matches ──────────────────────────────────────────

function buildSpans(data: EngineReport, filter: ReportFilter): Span[] {
  const spans: Span[] = []

  data.sources.forEach((src, srcIdx) => {
    src.matches.forEach(m => {
      if (filter === 'exact'      && m.detection === 'paraphrase') return
      if (filter === 'paraphrase' && m.detection !== 'paraphrase') return

      const start = (m as any).query_char_start ?? -1
      const end   = (m as any).query_char_end   ?? -1
      if (start === -1 || end === -1 || end <= start) return

      spans.push({
        start,
        end,
        sourceIdx: srcIdx,
        isExact:   m.detection !== 'paraphrase',
      })
    })
  })

  // Sort by start, merge overlapping spans (keep highest sourceIdx color)
  spans.sort((a, b) => a.start - b.start)
  const merged: Span[] = []
  for (const span of spans) {
    const prev = merged[merged.length - 1]
    if (prev && span.start < prev.end) {
      prev.end = Math.max(prev.end, span.end)
    } else {
      merged.push({ ...span })
    }
  }
  return merged
}

/** Returns which span index covers charPos, or -1 if clean. */
function spanAt(charPos: number, spans: Span[]): number {
  for (let i = 0; i < spans.length; i++) {
    if (charPos >= spans[i].start && charPos < spans[i].end) return i
    if (spans[i].start > charPos) break
  }
  return -1
}

// ── Highlight colors ──────────────────────────────────────────────────────────

function highlightBg(span: Span) {
  return span.isExact ? C.redBg : C.purpleBg
}

// ── Legend ────────────────────────────────────────────────────────────────────

function renderLegend(doc: jsPDF, data: EngineReport, y: number): number {
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(FONT_TINY)
  doc.setTextColor(...C.textMuted)
  doc.text('SOURCE LEGEND', ML, y)
  y += 4

  data.sources.forEach((src, i) => {
    const isExact = src.has_exact_copies
    const col     = isExact ? C.red : C.purple

    // Colored dot
    doc.setFillColor(...col)
    doc.circle(ML + 2.5, y + 2.5, 2.5, 'F')

    // Number
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(5.5)
    doc.setTextColor(...C.white)
    doc.text(String(i + 1), ML + 2.5, y + 4.3, { align: 'center' })

    // Title
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(FONT_SMALL)
    doc.setTextColor(...C.textMain)
    const titleLines = wrap(doc, src.title || src.arxiv_id, CW - 30)
    doc.text(titleLines[0], ML + 8, y + 4)

    // Sim %
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(FONT_SMALL)
    doc.setTextColor(...col)
    doc.text(`${src.average_similarity_percent.toFixed(1)}%`, PW - MR, y + 4, { align: 'right' })

    y += 8
  })

  return y + 2
}

// ── Main renderer ─────────────────────────────────────────────────────────────

export function renderDocumentView(
  doc:          jsPDF,
  data:         EngineReport,
  totalPages:   number,
  fileName:     string,
  submissionId: string,
  date:         string,
  filter:       ReportFilter,
) {
  const fullText = (data as any).full_text as string | undefined
  if (!fullText) return

  const spans = buildSpans(data, filter)

  addPage(doc)
  let pg = currentPage(doc)
  pageHeader(doc, fileName, pg, totalPages)
  pageFooter(doc, submissionId, date)

  let y = MT + 6

  // Page title
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(FONT_HEAD)
  doc.setTextColor(...C.textMain)
  doc.text('Document View', ML, y)
  y += 5

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(FONT_SMALL)
  doc.setTextColor(...C.textMuted)
  doc.text('Highlighted passages were flagged as potentially plagiarised.', ML, y)
  y += 8

  // Legend
  y = renderLegend(doc, data, y)

  // Divider
  doc.setDrawColor(...C.border)
  doc.setLineWidth(0.25)
  doc.line(ML, y, PW - MR, y)
  y += 8

  // ── Flowing text with inline highlights ──────────────────────────────────

  // We split the full text into words, track char position of each word,
  // then lay them out line by line. Before rendering each word we check
  // if it falls inside a flagged span and draw a highlight rect behind it.

  const FONT_SIZE   = FONT_BODY
  const SPACE_W     = 1.8    // approximate space width in mm at FONT_BODY
  const LINE_HEIGHT = LINE_H + 1.5
  const HIGHLIGHT_H = LINE_HEIGHT - 0.5   // height of highlight rect per line

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(FONT_SIZE)

  // Split full text into words with their char offsets
  const words: Array<{ word: string; start: number; end: number }> = []
  const wordRegex = /\S+/g
  let match: RegExpExecArray | null
  while ((match = wordRegex.exec(fullText)) !== null) {
    words.push({ word: match[0], start: match.index, end: match.index + match[0].length })
  }

  // Layout: greedily pack words into lines up to CW
  interface LayoutLine {
    words: Array<{ word: string; start: number; end: number; x: number; w: number }>
  }

  const lines: LayoutLine[] = []
  let currentLine: LayoutLine = { words: [] }
  let lineWidth = 0

  for (const w of words) {
    const ww = doc.getTextWidth(w.word)
    const needed = lineWidth === 0 ? ww : lineWidth + SPACE_W + ww

    if (needed > CW && currentLine.words.length > 0) {
      lines.push(currentLine)
      currentLine = { words: [] }
      lineWidth = 0
    }

    const x = ML + (lineWidth === 0 ? 0 : lineWidth + SPACE_W)
    currentLine.words.push({ ...w, x, w: ww })
    lineWidth = lineWidth === 0 ? ww : lineWidth + SPACE_W + ww
  }
  if (currentLine.words.length > 0) lines.push(currentLine)

  // Render lines
  for (const line of lines) {
    // Overflow — new page
    if (y + LINE_HEIGHT > PH - 14) {
      addPage(doc)
      pg = currentPage(doc)
      pageHeader(doc, fileName, pg, totalPages)
      pageFooter(doc, submissionId, date)
      y = MT + 6
    }

    // Render each word in the line
    for (const wd of line.words) {
      const si = spanAt(wd.start, spans)

      if (si !== -1) {
        const span = spans[si]
        const bg   = highlightBg(span)

        // Highlight rect behind this word — slightly taller than text
        doc.setFillColor(...bg)
        doc.rect(wd.x - 0.3, y - LINE_HEIGHT + 1.5, wd.w + 0.6, HIGHLIGHT_H, 'F')
      }

      // Word text
      doc.setFont('helvetica', 'normal')
      doc.setFontSize(FONT_SIZE)
      doc.setTextColor(...C.textMain)
      doc.text(wd.word, wd.x, y)
    }

    y += LINE_HEIGHT
  }
}