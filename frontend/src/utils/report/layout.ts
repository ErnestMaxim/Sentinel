import jsPDF from 'jspdf'
import { C, CW, FONT_TINY, ML, MR, PH, PW } from './helpers/constants'
import { fillRect, wrap } from './primitives'

export function pageHeader(
  doc:        jsPDF,
  docName:    string,
  pageNum:    number,
  totalPages: number,
) {
  const H = 14

  // Background
  fillRect(doc, 0, 0, PW, H, C.pageBg)

  // Yellow left accent bar
  fillRect(doc, 0, 0, 4, H, C.yellow)

  // Bottom border
  doc.setDrawColor(...C.border)
  doc.setLineWidth(0.3)
  doc.line(0, H, PW, H)

  // Wordmark
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(8)
  doc.setTextColor(...C.textMain)
  doc.text('SENTINEL', ML, H / 2 + 2.5)

  // Separator dot
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(FONT_TINY)
  doc.setTextColor(...C.textDim)
  doc.text('·', ML + 22, H / 2 + 2.5)

  // Doc name
  const nameMaxW = CW - 50
  const nameLines = wrap(doc, docName, nameMaxW)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(FONT_TINY)
  doc.setTextColor(...C.textMuted)
  doc.text(nameLines[0], ML + 27, H / 2 + 2.5)

  // Page counter — right aligned
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(FONT_TINY)
  doc.setTextColor(...C.textDim)
  doc.text(`${pageNum} / ${totalPages}`, PW - MR, H / 2 + 2.5, { align: 'right' })
}

export function pageFooter(doc: jsPDF, submissionId: string, date: string) {
  const H = 10

  fillRect(doc, 0, PH - H, PW, H, C.pageBg)

  doc.setDrawColor(...C.border)
  doc.setLineWidth(0.3)
  doc.line(0, PH - H, PW, PH - H)

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(FONT_TINY)
  doc.setTextColor(...C.textDim)
  doc.text(`ID: ${submissionId}`, ML, PH - 3.5)
  doc.text(date, PW - MR, PH - 3.5, { align: 'right' })
}