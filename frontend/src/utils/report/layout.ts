// ── layout.ts ─────────────────────────────────────────────────────────────────

import jsPDF from 'jspdf'
import { C, CW, FONT_TINY, ML, MR, PH, PW } from './helpers/constants'
import { fillRect, wrap } from './primitives'

export function pageHeader(
  doc:        jsPDF,
  docName:    string,
  pageNum:    number,
  totalPages: number,
) {
  // Clean white header — just a subtle bottom border
  fillRect(doc, 0, 0, PW, 12, C.pageBg)
  doc.setDrawColor(...C.border)
  doc.setLineWidth(0.25)
  doc.line(0, 12, PW, 12)

  // Wordmark — small, yellow
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(7)
  doc.setTextColor(...C.yellowText)
  doc.text('SENTINEL', ML, 8)

  // Doc name
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(FONT_TINY)
  doc.setTextColor(...C.textDim)
  const nameLines = wrap(doc, docName, CW - 40)
  doc.text(nameLines[0], ML + 20, 8)

  // Page counter
  doc.setTextColor(...C.textDim)
  doc.text(`${pageNum} / ${totalPages}`, PW - MR, 8, { align: 'right' })
}

export function pageFooter(doc: jsPDF, submissionId: string, date: string) {
  fillRect(doc, 0, PH - 10, PW, 10, C.pageBg)
  doc.setDrawColor(...C.border)
  doc.setLineWidth(0.25)
  doc.line(0, PH - 10, PW, PH - 10)

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(FONT_TINY)
  doc.setTextColor(...C.textDim)
  doc.text(`ID: ${submissionId}`, ML, PH - 4)
  doc.text(date, PW - MR, PH - 4, { align: 'right' })
}