import jsPDF from 'jspdf'
import { C, ML, MR, PH, PW, type RGB } from './helpers/constants'

export function wrap(doc: jsPDF, text: string, maxW: number): string[] {
  return doc.splitTextToSize(String(text ?? ''), maxW)
}

export function hLine(doc: jsPDF, y: number, color: RGB = C.border, lw = 0.25) {
  doc.setDrawColor(...color)
  doc.setLineWidth(lw)
  doc.line(ML, y, PW - MR, y)
}

export function fillRect(doc: jsPDF, x: number, y: number, w: number, h: number, color: RGB) {
  doc.setFillColor(...color)
  doc.rect(x, y, w, h, 'F')
}

/** Rounded filled rectangle. r = corner radius in mm. */
export function fillRounded(doc: jsPDF, x: number, y: number, w: number, h: number, r: number, color: RGB) {
  doc.setFillColor(...color)
  doc.roundedRect(x, y, w, h, r, r, 'F')
}

/** Rounded stroked rectangle. */
export function strokeRounded(doc: jsPDF, x: number, y: number, w: number, h: number, r: number, color: RGB, lw = 0.3) {
  doc.setDrawColor(...color)
  doc.setLineWidth(lw)
  doc.roundedRect(x, y, w, h, r, r, 'S')
}

export function addPage(doc: jsPDF) {
  doc.addPage()
  fillRect(doc, 0, 0, PW, PH, C.pageBg)
}

export function currentPage(doc: jsPDF): number {
  return (doc.internal as any).getCurrentPageInfo().pageNumber as number
}