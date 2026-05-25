import jsPDF from 'jspdf'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface EngineMatch {
  query_chunk_idx:      number
  query_text:           string
  db_chunk_idx:         number
  db_text:              string
  cosine_similarity:    number
  match_percentage:     number
  exact_copied_phrases: string[]
  db_source_type:       string
  detection?:           'exact' | 'paraphrase'
}

export interface EngineSource {
  arxiv_id:                    string
  title:                       string
  match_count:                 number
  average_similarity_percent:  number
  has_exact_copies:            boolean
  score_contribution_percent?: number
  matches:                     EngineMatch[]
}

export interface EngineReport {
  file_name?:                      string
  global_plagiarism_score_percent: number
  total_suspicious_sources:        number
  total_reported_sources:          number
  document_stats: {
    total_words:           number
    total_chunks_analyzed: number
  }
  analysis_config: {
    threshold_used:   number
    embedding_model:  string
    category_routing: { enabled: boolean; routed_to: string[] | null }
  }
  sources: EngineSource[]
}

export type ReportFilter = 'all' | 'exact' | 'paraphrase'

// ── Layout constants ──────────────────────────────────────────────────────────

const PW   = 210   // A4 width mm
const PH   = 297   // A4 height mm
const ML   = 20    // margin left
const MR   = 20    // margin right
const MT   = 20    // margin top
const CW   = PW - ML - MR

// ── Colour palette (all light-mode) ──────────────────────────────────────────

const C = {
  black:      [15,  15,  20]  as [number,number,number],
  grey:       [100, 100, 110] as [number,number,number],
  lightGrey:  [220, 220, 225] as [number,number,number],
  bgGrey:     [248, 248, 250] as [number,number,number],
  white:      [255, 255, 255] as [number,number,number],
  accent:     [30,  30,  30]  as [number,number,number],   // dark text on yellow
  yellow:     [255, 215,   0] as [number,number,number],   // Sentinel yellow
  yellowBg:   [255, 250, 210] as [number,number,number],
  red:        [200,  50,  50] as [number,number,number],
  redBg:      [255, 240, 240] as [number,number,number],
  purple:     [130,  60, 200] as [number,number,number],
  purpleBg:   [245, 235, 255] as [number,number,number],
  green:      [30,  160,  80] as [number,number,number],
  greenBg:    [230, 250, 238] as [number,number,number],
  orange:     [200, 100,  20] as [number,number,number],
  orangeBg:   [255, 243, 225] as [number,number,number],
  blue:       [30,  100, 200] as [number,number,number],
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function scoreColor(pct: number): [number,number,number] {
  if (pct <= 15) return C.green
  if (pct <= 40) return C.orange
  return C.red
}

function scoreBgColor(pct: number): [number,number,number] {
  if (pct <= 15) return C.greenBg
  if (pct <= 40) return C.orangeBg
  return C.redBg
}

function wrap(doc: jsPDF, text: string, maxW: number): string[] {
  return doc.splitTextToSize(String(text ?? ''), maxW)
}

function hLine(doc: jsPDF, y: number, color = C.lightGrey, lw = 0.3) {
  doc.setDrawColor(...color)
  doc.setLineWidth(lw)
  doc.line(ML, y, PW - MR, y)
}

function fillRect(doc: jsPDF, x: number, y: number, w: number, h: number, color: [number,number,number]) {
  doc.setFillColor(...color)
  doc.rect(x, y, w, h, 'F')
}

function addPage(doc: jsPDF) {
  doc.addPage()
  fillRect(doc, 0, 0, PW, PH, C.white)
}

// ── Header / footer printed on every page ────────────────────────────────────

function pageHeader(doc: jsPDF, docName: string, pageNum: number, totalPages: number) {
  // Top yellow bar
  fillRect(doc, 0, 0, PW, 12, C.yellow)

  // "SENTINEL" wordmark
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(8)
  doc.setTextColor(...C.black)
  doc.text('SENTINEL', ML, 8)

  // doc name truncated
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7)
  doc.setTextColor(60, 60, 60)
  const maxNameW = CW - 40
  const nameLines = wrap(doc, docName, maxNameW)
  doc.text(nameLines[0], ML + 22, 8)

  // page number right
  doc.setTextColor(80, 80, 80)
  doc.text(`${pageNum} / ${totalPages}`, PW - MR, 8, { align: 'right' })
}

function pageFooter(doc: jsPDF, submissionId: string, date: string) {
  hLine(doc, PH - 10, C.lightGrey)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7)
  doc.setTextColor(...C.grey)
  doc.text(`Submission ID: ${submissionId}`, ML, PH - 5)
  doc.text(date, PW - MR, PH - 5, { align: 'right' })
}

// ── Page 1: Cover ─────────────────────────────────────────────────────────────

function renderCover(
  doc: jsPDF,
  data: EngineReport,
  submissionId: string,
  date: string,
  filter: ReportFilter,
  totalPages: number,
) {
  const fileName = data.file_name ?? 'Document'
  pageHeader(doc, fileName, 1, totalPages)
  pageFooter(doc, submissionId, date)

  let y = MT + 8

  // ── Title block ──────────────────────────────────────────────────────────
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(22)
  doc.setTextColor(...C.black)
  doc.text('Originality Report', ML, y)
  y += 7

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  doc.setTextColor(...C.grey)
  doc.text('Sentinel Anti-Plagiarism Platform', ML, y)
  y += 8

  hLine(doc, y, C.lightGrey, 0.5)
  y += 7

  // ── File name ────────────────────────────────────────────────────────────
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(11)
  doc.setTextColor(...C.black)
  const nameLines = wrap(doc, fileName, CW)
  doc.text(nameLines, ML, y)
  y += nameLines.length * 5.5 + 3

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8)
  doc.setTextColor(...C.grey)
  doc.text(`Submitted: ${date}`, ML, y);    y += 4.5
  doc.text(`Submission ID: ${submissionId}`, ML, y); y += 4.5

  const filterLabel = filter === 'exact' ? 'Exact matches only'
    : filter === 'paraphrase' ? 'Paraphrases only' : 'All matches'
  doc.text(`Report filter: ${filterLabel}`, ML, y)
  y += 10

  // ── Score card ───────────────────────────────────────────────────────────
  const sim    = data.global_plagiarism_score_percent ?? 0
  const sCol   = scoreColor(sim)
  const sBgCol = scoreBgColor(sim)

  fillRect(doc, ML, y, CW, 28, C.bgGrey)
  doc.setDrawColor(...C.lightGrey)
  doc.setLineWidth(0.3)
  doc.rect(ML, y, CW, 28)

  // Left: big score
  fillRect(doc, ML, y, 44, 28, sBgCol)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(22)
  doc.setTextColor(...sCol)
  doc.text(`${sim.toFixed(1)}%`, ML + 22, y + 13, { align: 'center' })
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(6.5)
  doc.setTextColor(...sCol)
  doc.text('SIMILARITY', ML + 22, y + 20, { align: 'center' })

  // Right: three stats
  const stats = [
    { label: 'Sources Found',    val: String(data.total_reported_sources ?? data.sources?.length ?? 0) },
    { label: 'Chunks Analyzed',  val: String(data.document_stats?.total_chunks_analyzed ?? 0) },
    { label: 'Total Words',      val: (data.document_stats?.total_words ?? 0).toLocaleString() },
  ]
  const colW = (CW - 48) / stats.length
  stats.forEach((s, i) => {
    const sx = ML + 48 + i * colW + colW / 2
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(14)
    doc.setTextColor(...C.black)
    doc.text(s.val, sx, y + 13, { align: 'center' })
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(6.5)
    doc.setTextColor(...C.grey)
    doc.text(s.label.toUpperCase(), sx, y + 20, { align: 'center' })

    if (i < stats.length - 1) {
      doc.setDrawColor(...C.lightGrey)
      doc.setLineWidth(0.3)
      doc.line(ML + 48 + (i + 1) * colW, y + 4, ML + 48 + (i + 1) * colW, y + 24)
    }
  })
  y += 34

  // ── Sources table ────────────────────────────────────────────────────────
  if ((data.sources?.length ?? 0) === 0) {
    fillRect(doc, ML, y, CW, 20, C.greenBg)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(10)
    doc.setTextColor(...C.green)
    doc.text('✓  No plagiarism detected — your document appears to be original.', ML + 6, y + 13)
    return
  }

  // Table header
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(9)
  doc.setTextColor(...C.black)
  doc.text('Matched Sources', ML, y)
  y += 5
  hLine(doc, y, C.black, 0.5)
  y += 3

  // Column header row
  fillRect(doc, ML, y, CW, 6, C.bgGrey)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(7)
  doc.setTextColor(...C.grey)
  doc.text('TYPE',   ML + 2,          y + 4)
  doc.text('SOURCE', ML + 24,         y + 4)
  doc.text('MATCHES',PW - MR - 38,    y + 4, { align: 'right' })
  doc.text('SIM %',  PW - MR,         y + 4, { align: 'right' })
  y += 6
  hLine(doc, y, C.lightGrey)
  y += 1

  data.sources.forEach((src, i) => {
    if (y > PH - 22) return   // overflow guard

    const rowH  = 13
    const isOdd = i % 2 === 1
    if (isOdd) fillRect(doc, ML, y, CW, rowH, C.bgGrey)

    // Detection badge
    const isExact   = src.has_exact_copies
    const badgeCol  = isExact ? C.red : C.purple
    const badgeBg   = isExact ? C.redBg : C.purpleBg
    const badgeTxt  = isExact ? 'EXACT' : 'PARA.'
    fillRect(doc, ML + 1, y + 2, 18, 5, badgeBg)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(5.5)
    doc.setTextColor(...badgeCol)
    doc.text(badgeTxt, ML + 10, y + 5.8, { align: 'center' })

    // Source number + title
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(8)
    doc.setTextColor(...C.black)
    const titleLines = wrap(doc, `${i + 1}.  ${src.title || src.arxiv_id}`, CW - 60)
    doc.text(titleLines[0], ML + 24, y + 5.5)

    // arXiv link
    doc.setFontSize(6.5)
    doc.setTextColor(...C.blue)
    doc.text(`arxiv.org/abs/${src.arxiv_id}`, ML + 24, y + 10)
    doc.link(ML + 24, y + 7, 65, 4, { url: `https://arxiv.org/abs/${src.arxiv_id}` })

    // Match count
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(8)
    doc.setTextColor(...C.grey)
    doc.text(`${src.match_count}`, PW - MR - 38, y + 6, { align: 'right' })

    // Similarity %
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(9)
    doc.setTextColor(...scoreColor(src.average_similarity_percent))
    doc.text(`${src.average_similarity_percent.toFixed(1)}%`, PW - MR, y + 6, { align: 'right' })

    y += rowH
    hLine(doc, y, C.lightGrey, 0.2)
  })
}

// ── Pages 2+: Per-source detail ───────────────────────────────────────────────

function renderSource(
  doc: jsPDF,
  src: EngineSource,
  srcIndex: number,
  pageNum: number,
  totalPages: number,
  fileName: string,
  submissionId: string,
  date: string,
  filter: ReportFilter,
) {
  pageHeader(doc, fileName, pageNum, totalPages)
  pageFooter(doc, submissionId, date)

  const filteredMatches = src.matches.filter(m => {
    if (filter === 'exact')      return m.detection !== 'paraphrase'
    if (filter === 'paraphrase') return m.detection === 'paraphrase'
    return true
  })

  let y = MT + 8

  // ── Source header ────────────────────────────────────────────────────────
  const isExact  = src.has_exact_copies
  const hBgCol   = isExact ? C.redBg : C.purpleBg
  const hCol     = isExact ? C.red   : C.purple
  const hLabel   = isExact ? 'EXACT COPY' : 'PARAPHRASE'

  fillRect(doc, ML, y, CW, 24, hBgCol)
  doc.setDrawColor(...hCol)
  doc.setLineWidth(0.4)
  doc.rect(ML, y, CW, 24)

  // Left: source number badge
  fillRect(doc, ML, y, 12, 24, hCol)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(9)
  doc.setTextColor(...C.white)
  doc.text(String(srcIndex + 1), ML + 6, y + 14, { align: 'center' })

  // Detection label
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(6.5)
  doc.setTextColor(...hCol)
  doc.text(hLabel, ML + 16, y + 5.5)

  // Title
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(9.5)
  doc.setTextColor(...C.black)
  const titleLines = wrap(doc, src.title || src.arxiv_id, CW - 60)
  doc.text(titleLines[0], ML + 16, y + 11)

  // arXiv link
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7)
  doc.setTextColor(...C.blue)
  doc.text(`https://arxiv.org/abs/${src.arxiv_id}`, ML + 16, y + 17)
  doc.link(ML + 16, y + 13, 80, 5, { url: `https://arxiv.org/abs/${src.arxiv_id}` })

  // Right: similarity
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(18)
  doc.setTextColor(...scoreColor(src.average_similarity_percent))
  doc.text(`${src.average_similarity_percent.toFixed(1)}%`, PW - MR - 2, y + 14, { align: 'right' })
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(6.5)
  doc.setTextColor(...C.grey)
  doc.text(`${src.match_count} match${src.match_count !== 1 ? 'es' : ''}`, PW - MR - 2, y + 20, { align: 'right' })

  y += 30

  if (filteredMatches.length === 0) {
    doc.setFont('helvetica', 'italic')
    doc.setFontSize(9)
    doc.setTextColor(...C.grey)
    doc.text(`No ${filter} matches for this source.`, ML, y)
    return
  }

  // ── Match pairs ──────────────────────────────────────────────────────────
  filteredMatches.forEach((m, mi) => {
    const isParaphrase = m.detection === 'paraphrase'
    const mCol  = isParaphrase ? C.purple : C.red
    const mBg   = isParaphrase ? C.purpleBg : C.redBg
    const mLabel = isParaphrase ? '⟳ Paraphrase' : '≡ Exact match'

    // Estimate block height to check overflow
    const yourLines = wrap(doc, m.query_text || '', CW - 8)
    const dbLines   = m.db_text ? wrap(doc, m.db_text, CW - 8) : []
    const phLines   = (m.exact_copied_phrases ?? []).flatMap(ph => wrap(doc, `"${ph}"`, CW - 12))
    const estH = 10 + yourLines.length * 4.2 + (dbLines.length ? 6 + dbLines.length * 4.2 : 0) + (phLines.length ? 5 + phLines.length * 4 : 0) + 10

    if (y + estH > PH - 16) {
      addPage(doc)
      pageHeader(doc, fileName, pageNum, totalPages)
      pageFooter(doc, submissionId, date)
      y = MT + 8
    }

    // Match header row
    fillRect(doc, ML, y, CW, 6.5, mBg)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(7)
    doc.setTextColor(...mCol)
    doc.text(`${mi + 1}.  ${mLabel}`, ML + 3, y + 4.5)
    doc.setFont('helvetica', 'normal')
    doc.setTextColor(...C.grey)
    doc.text(`${m.match_percentage.toFixed(1)}% similarity`, PW - MR - 2, y + 4.5, { align: 'right' })
    y += 7.5

    // Progress bar
    const barW = CW
    fillRect(doc, ML, y, barW, 1.5, C.lightGrey)
    fillRect(doc, ML, y, barW * m.match_percentage / 100, 1.5, mCol)
    y += 4

    // ── Your text ──────────────────────────────────────────────────────────
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(6.5)
    doc.setTextColor(...C.grey)
    doc.text('YOUR TEXT', ML, y)
    y += 3.5

    const yourH = yourLines.length * 4.2 + 5
    fillRect(doc, ML, y, CW, yourH, C.bgGrey)
    doc.setDrawColor(...C.lightGrey)
    doc.setLineWidth(0.2)
    doc.rect(ML, y, CW, yourH)

    doc.setFont('helvetica', 'italic')
    doc.setFontSize(8)
    doc.setTextColor(...C.black)
    yourLines.forEach((line, li) => doc.text(line, ML + 3, y + 4 + li * 4.2))
    y += yourH + 2

    // ── Matched source text ────────────────────────────────────────────────
    if (dbLines.length) {
      doc.setFont('helvetica', 'bold')
      doc.setFontSize(6.5)
      doc.setTextColor(...C.grey)
      doc.text('MATCHED SOURCE TEXT', ML, y)
      y += 3.5

      const dbH = dbLines.length * 4.2 + 5
      fillRect(doc, ML, y, 2, dbH, mCol)
      fillRect(doc, ML + 2, y, CW - 2, dbH, mBg)
      doc.setDrawColor(...C.lightGrey)
      doc.setLineWidth(0.2)
      doc.rect(ML + 2, y, CW - 2, dbH)

      doc.setFont('helvetica', 'normal')
      doc.setFontSize(8)
      doc.setTextColor(50, 50, 60)
      dbLines.forEach((line, li) => doc.text(line, ML + 5, y + 4 + li * 4.2))
      y += dbH + 2
    }

    // ── Exact phrases ──────────────────────────────────────────────────────
    if (phLines.length) {
      doc.setFont('helvetica', 'bold')
      doc.setFontSize(6.5)
      doc.setTextColor(...C.red)
      doc.text('EXACT COPIED PHRASES:', ML, y)
      y += 3.5
      doc.setFont('helvetica', 'italic')
      doc.setFontSize(7.5)
      doc.setTextColor(...C.red)
      phLines.forEach(line => { doc.text(line, ML + 3, y); y += 4 })
      y += 2
    }

    y += 4
    hLine(doc, y - 1, C.lightGrey, 0.3)
    y += 4
  })
}

// ── Main export ───────────────────────────────────────────────────────────────

export async function generatePdfReport(
  data: EngineReport,
  originalFileName: string,
  filter: ReportFilter = 'all',
): Promise<void> {
  // Guard against undefined/null fields from the API to prevent PDF render crashes
  const safeData: EngineReport = {
    ...data,
    global_plagiarism_score_percent: data.global_plagiarism_score_percent ?? 0,
    total_reported_sources: data.total_reported_sources ?? 0,
    total_suspicious_sources: data.total_suspicious_sources ?? 0,
    document_stats: {
      total_words: data.document_stats?.total_words ?? 0,
      total_chunks_analyzed: data.document_stats?.total_chunks_analyzed ?? 0,
    },
    sources: data.sources ?? [],
  }

  const fileName     = safeData.file_name ?? originalFileName
  const submissionId = `sentinel:${Date.now()}`
  const date         = new Date().toLocaleString('en-GB')
  const baseName     = fileName.replace(/\.[^/.]+$/, '')
  const suffix       = filter !== 'all' ? `_${filter}` : ''
  
  // Calculate total pages: Cover page + one page per source
  const totalPages   = 1 + (safeData.sources.length)

  const doc = new jsPDF({ unit: 'mm', format: 'a4', compress: true })
  
  // Initial background fill
  fillRect(doc, 0, 0, PW, PH, C.white)

  // Render the Cover Page (Page 1)
  renderCover(doc, safeData, submissionId, date, filter, totalPages)

  // Render detail pages for each source
  safeData.sources.forEach((src, i) => {
    addPage(doc)
    renderSource(
      doc, 
      src, 
      i, 
      i + 2, 
      totalPages, 
      fileName, 
      submissionId, 
      date, 
      filter
    )
  })

  doc.save(`plagiarism_report_${baseName}${suffix}.pdf`)
}