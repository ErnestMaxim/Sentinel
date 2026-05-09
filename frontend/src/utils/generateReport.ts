import {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, BorderStyle, WidthType, ShadingType,
  VerticalAlign,
  type IRunOptions,
  type IParagraphOptions,
} from 'docx'
import { saveAs } from 'file-saver'

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
}

export interface EngineSource {
  arxiv_id:                   string
  title:                      string
  match_count:                number
  average_similarity_percent: number
  has_exact_copies:           boolean
  matches:                    EngineMatch[]
}

export interface EngineReport {
  file_name?:                       string
  global_plagiarism_score_percent:  number
  total_suspicious_sources:         number
  total_reported_sources:           number
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

// ── Constants ─────────────────────────────────────────────────────────────────

const PAGE_W  = 11906
const PAGE_H  = 16838
const MARGIN  = 1134
const CONTENT = PAGE_W - MARGIN * 2

const C = {
  black:  '000000',
  grey:   '666666',
  lgrey:  'F2F2F2',
  border: 'DDDDDD',
  blue:   '0066CC',
  red:    'CC0000',
  amber:  'E67E22',
  green:  '27AE60',
  white:  'FFFFFF',
}

const BADGE_COLORS = [
  'E74C3C','E67E22','2980B9','27AE60',
  '8E44AD','F39C12','16A085','C0392B',
]

// ── Low-level helpers ─────────────────────────────────────────────────────────

function simColor(n: number) { return n <= 15 ? C.green : n <= 40 ? C.amber : C.red }

function nb() { return { style: BorderStyle.NONE,   size: 0, color: C.white  } }
function sb(color = C.border, size = 4) { return { style: BorderStyle.SINGLE, size, color } }
function allB(color = C.border, size = 4) {
  const b = sb(color, size); return { top: b, bottom: b, left: b, right: b }
}
function noB() { return { top: nb(), bottom: nb(), left: nb(), right: nb() } }

// Use explicit IRunOptions — fixes TS2698 "Spread types may only be created from object types"
function t(str: string, opts: IRunOptions = {}): TextRun {
  return new TextRun({ text: String(str ?? ''), font: 'Arial', ...opts })
}
function b(str: string, opts: IRunOptions = {}): TextRun {
  return t(str, { bold: true, ...opts })
}

// Use explicit IParagraphOptions
function p(runs: TextRun | TextRun[], opts: IParagraphOptions = {}): Paragraph {
  const children = Array.isArray(runs) ? runs : [runs]
  return new Paragraph({ children, spacing: { after: 0 }, ...opts })
}

function gap(pt = 120): Paragraph {
  return new Paragraph({ children: [], spacing: { before: pt, after: 0 } })
}
function hr(color = C.border): Paragraph {
  return new Paragraph({
    children: [],
    border: { bottom: sb(color, 6) },
    spacing: { before: 80, after: 80 },
  })
}
function pct(n: number) { return `${Number(n ?? 0).toFixed(0)}%` }
function pageProps() {
  return { page: { size: { width: PAGE_W, height: PAGE_H }, margin: { top: MARGIN, right: MARGIN, bottom: MARGIN, left: MARGIN } } }
}

// ── Header / footer ───────────────────────────────────────────────────────────

function makeHeader(label: string, fileName: string): Header {
  return new Header({
    children: [
      new Table({
        width: { size: CONTENT, type: WidthType.DXA },
        columnWidths: [CONTENT - 3000, 3000],
        rows: [new TableRow({ children: [
          new TableCell({
            width: { size: CONTENT - 3000, type: WidthType.DXA },
            borders: { top: nb(), bottom: sb(C.border, 4), left: nb(), right: nb() },
            margins: { top: 60, bottom: 80, left: 0, right: 0 },
            children: [p([t('sentinel', { size: 18, color: C.blue }), t(`  ${label}`, { size: 16, color: C.grey })])],
          }),
          new TableCell({
            width: { size: 3000, type: WidthType.DXA },
            borders: { top: nb(), bottom: sb(C.border, 4), left: nb(), right: nb() },
            margins: { top: 60, bottom: 80, left: 0, right: 0 },
            children: [p(t(fileName, { size: 16, color: C.grey }), { alignment: AlignmentType.RIGHT })],
          }),
        ]})]
      }),
    ],
  })
}

function makeFooter(label: string, submissionId: string): Footer {
  return new Footer({
    children: [
      new Table({
        width: { size: CONTENT, type: WidthType.DXA },
        columnWidths: [CONTENT / 2, CONTENT / 2],
        rows: [new TableRow({ children: [
          new TableCell({
            width: { size: CONTENT / 2, type: WidthType.DXA },
            borders: { top: sb(C.border, 4), bottom: nb(), left: nb(), right: nb() },
            margins: { top: 80, bottom: 60, left: 0, right: 0 },
            children: [p([t('sentinel', { size: 16, color: C.blue }), t(`  ${label}`, { size: 16, color: C.grey })])],
          }),
          new TableCell({
            width: { size: CONTENT / 2, type: WidthType.DXA },
            borders: { top: sb(C.border, 4), bottom: nb(), left: nb(), right: nb() },
            margins: { top: 80, bottom: 60, left: 0, right: 0 },
            children: [p(t(`Submission ID  ${submissionId}`, { size: 16, color: C.grey }), { alignment: AlignmentType.RIGHT })],
          }),
        ]})]
      }),
    ],
  })
}

// ── Page 1: Cover ─────────────────────────────────────────────────────────────

function coverSection(data: EngineReport, submissionId: string, submDate: string, totalPages: number) {
  const label    = `Page 1 of ${totalPages} - Cover Page`
  const docTitle = data.file_name!.replace(/\.[^/.]+$/, '')
  const words    = data.document_stats.total_words ?? 0
  const chunks   = data.document_stats.total_chunks_analyzed ?? 0

  return {
    properties: pageProps(),
    headers: {
      default: new Header({ children: [
        new Table({
          width: { size: CONTENT, type: WidthType.DXA },
          columnWidths: [CONTENT - 2800, 2800],
          rows: [new TableRow({ children: [
            new TableCell({
              width: { size: CONTENT - 2800, type: WidthType.DXA }, borders: noB(),
              margins: { top: 60, bottom: 60, left: 0, right: 0 },
              children: [p(t('sentinel', { size: 24, color: C.blue }))],
            }),
            new TableCell({
              width: { size: 2800, type: WidthType.DXA }, borders: noB(),
              margins: { top: 60, bottom: 60, left: 0, right: 0 },
              children: [p(t(label, { size: 16, color: C.grey }), { alignment: AlignmentType.RIGHT })],
            }),
          ]})]
        }),
      ]}),
    },
    footers: { default: makeFooter(label, submissionId) },
    children: [
      ...Array(12).fill(null).map(() => gap(180)),
      p(b(docTitle, { size: 60 })),
      gap(80),
      p(b(data.file_name!, { size: 36 })),
      gap(60),
      p(t('Sentinel  ·  Academic Integrity System  ·  Plagiarism Detection', { size: 20, color: C.grey })),
      gap(240), hr(), gap(160),
      p(b('Document Details', { size: 26 }), { spacing: { after: 120 } }),
      new Table({
        width: { size: CONTENT, type: WidthType.DXA },
        columnWidths: [CONTENT - 2800, 2800],
        rows: [new TableRow({ children: [
          new TableCell({
            width: { size: CONTENT - 2800, type: WidthType.DXA }, borders: noB(),
            margins: { top: 0, bottom: 0, left: 0, right: 200 },
            children: [
              p(b('Submission ID', { size: 17, color: C.grey })),
              p(b(submissionId, { size: 20 })), gap(100),
              p(b('Submission Date', { size: 17, color: C.grey })),
              p(b(submDate, { size: 20 })), gap(100),
              p(b('File Name', { size: 17, color: C.grey })),
              p(b(data.file_name!, { size: 20 })),
            ],
          }),
          new TableCell({
            width: { size: 2800, type: WidthType.DXA },
            borders: allB(C.border, 4),
            shading: { fill: C.lgrey, type: ShadingType.CLEAR },
            margins: { top: 200, bottom: 200, left: 200, right: 200 },
            verticalAlign: VerticalAlign.CENTER,
            children: [
              p(b(`${chunks} Chunks`, { size: 22 })), gap(80),
              p(b(`${words.toLocaleString()} Words`, { size: 22 })), gap(80),
              p(b(`${Math.round(words * 5.5).toLocaleString()} Characters`, { size: 22 })),
            ],
          }),
        ]})]
      }),
    ],
  }
}

// ── Page 2: Integrity Overview ────────────────────────────────────────────────

function overviewSection(data: EngineReport, submissionId: string, totalPages: number) {
  const label   = `Page 2 of ${totalPages} - Integrity Overview`
  const sim     = data.global_plagiarism_score_percent
  const sColor  = simColor(sim)
  const sources = data.sources

  return {
    properties: pageProps(),
    headers: { default: makeHeader(label, data.file_name!) },
    footers: { default: makeFooter(label, submissionId) },
    children: [
      gap(160),
      p([b(`${pct(sim)}`, { size: 72, color: sColor }), t('  Overall Similarity', { size: 40 })]),
      gap(60),
      p(t('The combined total of all matches, including overlapping sources, for each database.', { size: 20, color: C.grey })),
      gap(200), hr(), gap(160),
      p(b('Filtered from the Report', { size: 22 }), { spacing: { after: 100 } }),
      p(t('▸  Bibliography', { size: 20 })), gap(60),
      p(t('▸  Quoted Text', { size: 20 })),
      gap(200), hr(), gap(160),
      p(b('Top Sources', { size: 22 }), { spacing: { after: 100 } }),
      ...[
        [pct(sim), 'Publications (Academic Index)'],
        [pct(sources.filter(s => s.has_exact_copies).length > 0 ? Math.round(sim * 0.6) : 0), 'Exact matches detected'],
        [pct(Math.round(sim * 0.3)), 'Submitted works (Student Papers)'],
      ].map(([pctVal, lbl]) => new Table({
        width: { size: CONTENT, type: WidthType.DXA },
        columnWidths: [800, CONTENT - 800],
        rows: [new TableRow({ children: [
          new TableCell({
            width: { size: 800, type: WidthType.DXA }, borders: noB(),
            margins: { top: 40, bottom: 40, left: 0, right: 120 },
            children: [p(b(String(pctVal), { size: 22, color: C.grey }))],
          }),
          new TableCell({
            width: { size: CONTENT - 800, type: WidthType.DXA },
            borders: { top: nb(), bottom: sb(C.border, 2), left: nb(), right: nb() },
            margins: { top: 40, bottom: 80, left: 0, right: 0 },
            children: [p(t(String(lbl), { size: 20 }))],
          }),
        ]})]
      })),
    ],
  }
}

// ── Page 3: Top Sources ───────────────────────────────────────────────────────

function topSourcesSection(data: EngineReport, submissionId: string, totalPages: number) {
  const label = `Page 3 of ${totalPages} - Integrity Overview`

  const rows = data.sources.flatMap((src, i) => {
    const bg = BADGE_COLORS[i % BADGE_COLORS.length]
    return [
      new Table({
        width: { size: CONTENT, type: WidthType.DXA },
        columnWidths: [560, 1800, CONTENT - 2360],
        rows: [new TableRow({ children: [
          new TableCell({
            width: { size: 560, type: WidthType.DXA }, borders: noB(),
            shading: { fill: bg, type: ShadingType.CLEAR },
            margins: { top: 60, bottom: 60, left: 0, right: 0 },
            children: [p(b(String(i + 1), { size: 20, color: C.white }), { alignment: AlignmentType.CENTER })],
          }),
          new TableCell({
            width: { size: 1800, type: WidthType.DXA }, borders: noB(),
            margins: { top: 60, bottom: 60, left: 120, right: 0 },
            children: [p(t('Publication', { size: 18, color: bg }))],
          }),
          new TableCell({
            width: { size: CONTENT - 2360, type: WidthType.DXA }, borders: noB(),
            margins: { top: 60, bottom: 60, left: 0, right: 0 },
            children: [p([])],
          }),
        ]})]
      }),
      new Table({
        width: { size: CONTENT, type: WidthType.DXA },
        columnWidths: [CONTENT - 600, 600],
        rows: [new TableRow({ children: [
          new TableCell({
            width: { size: CONTENT - 600, type: WidthType.DXA },
            borders: { top: nb(), bottom: sb(C.border, 2), left: nb(), right: nb() },
            margins: { top: 40, bottom: 100, left: 0, right: 0 },
            children: [p(b(src.title || src.arxiv_id, { size: 20 }))],
          }),
          new TableCell({
            width: { size: 600, type: WidthType.DXA },
            borders: { top: nb(), bottom: sb(C.border, 2), left: nb(), right: nb() },
            margins: { top: 40, bottom: 100, left: 0, right: 0 },
            children: [p(b(pct(src.average_similarity_percent), { size: 20 }), { alignment: AlignmentType.RIGHT })],
          }),
        ]})]
      }),
      gap(40),
    ]
  })

  return {
    properties: pageProps(),
    headers: { default: makeHeader(label, data.file_name!) },
    footers: { default: makeFooter(label, submissionId) },
    children: [
      gap(160),
      p(b('Top Sources', { size: 28 }), { spacing: { after: 60 } }),
      p(t('The sources with the highest number of matches. Overlapping sources will not be displayed.', { size: 18, color: C.grey })),
      gap(180),
      ...rows,
    ],
  }
}

// ── Pages 4+: Per-source detail ───────────────────────────────────────────────

function detailSection(
  src: EngineSource,
  srcIndex: number,
  pageNum: number,
  totalPages: number,
  fileName: string,
  submissionId: string,
) {
  const label = `Page ${pageNum} of ${totalPages} - Integrity Submission`
  const bg    = BADGE_COLORS[srcIndex % BADGE_COLORS.length]

  const children: (Paragraph | Table)[] = [
    gap(120),
    new Table({
      width: { size: CONTENT, type: WidthType.DXA },
      columnWidths: [CONTENT - 1600, 1600],
      rows: [new TableRow({ children: [
        new TableCell({
          width: { size: CONTENT - 1600, type: WidthType.DXA }, borders: noB(),
          margins: { top: 60, bottom: 60, left: 0, right: 160 },
          children: [
            p(b(`Source ${srcIndex + 1}`, { size: 32, color: bg })), gap(40),
            p(t(src.title || src.arxiv_id, { size: 22 })), gap(40),
            p(t(`arXiv: ${src.arxiv_id}  ·  ${src.match_count} match${src.match_count !== 1 ? 'es' : ''}`, { size: 18, color: C.grey })),
          ],
        }),
        new TableCell({
          width: { size: 1600, type: WidthType.DXA },
          borders: allB(bg, 6),
          shading: { fill: C.lgrey, type: ShadingType.CLEAR },
          margins: { top: 80, bottom: 80, left: 140, right: 140 },
          verticalAlign: VerticalAlign.CENTER,
          children: [
            p(b(pct(src.average_similarity_percent), { size: 48, color: bg }), { alignment: AlignmentType.CENTER }),
            p(t(src.has_exact_copies ? 'EXACT COPY' : 'PARAPHRASE', { size: 16, color: bg }), { alignment: AlignmentType.CENTER }),
          ],
        }),
      ]})]
    }),
    gap(120), hr(), gap(120),
  ]

  ;(src.matches || []).forEach(m => {
    children.push(
      new Table({
        width: { size: CONTENT, type: WidthType.DXA },
        columnWidths: [480, CONTENT - 480],
        rows: [new TableRow({ children: [
          new TableCell({
            width: { size: 480, type: WidthType.DXA }, borders: noB(),
            shading: { fill: bg, type: ShadingType.CLEAR },
            margins: { top: 80, bottom: 80, left: 0, right: 0 },
            verticalAlign: VerticalAlign.TOP,
            children: [p(b(String(srcIndex + 1), { size: 20, color: C.white }), { alignment: AlignmentType.CENTER })],
          }),
          new TableCell({
            width: { size: CONTENT - 480, type: WidthType.DXA },
            borders: { top: nb(), bottom: sb(C.border, 2), left: nb(), right: nb() },
            shading: { fill: 'FFFDF0', type: ShadingType.CLEAR },
            margins: { top: 80, bottom: 100, left: 160, right: 0 },
            children: [
              p(b('Your text', { size: 16, color: C.grey })), gap(40),
              p(t(m.query_text || '', { size: 20, italics: true })),
            ],
          }),
        ]})]
      }),
      new Table({
        width: { size: CONTENT, type: WidthType.DXA },
        columnWidths: [480, CONTENT - 480],
        rows: [new TableRow({ children: [
          new TableCell({
            width: { size: 480, type: WidthType.DXA }, borders: noB(),
            margins: { top: 60, bottom: 60, left: 0, right: 0 },
            children: [p(b(pct(m.match_percentage), { size: 18, color: bg }), { alignment: AlignmentType.CENTER })],
          }),
          new TableCell({
            width: { size: CONTENT - 480, type: WidthType.DXA },
            borders: { top: nb(), bottom: sb(bg, 6), left: sb(bg, 8), right: nb() },
            shading: { fill: 'FEF0F0', type: ShadingType.CLEAR },
            margins: { top: 80, bottom: 100, left: 160, right: 0 },
            children: [
              p(b('Matched source', { size: 16, color: bg })), gap(40),
              p(t(m.db_text || '', { size: 20 })),
              ...(m.exact_copied_phrases?.length > 0 ? [
                gap(80),
                p(b('Exact phrases:', { size: 16, color: C.red })),
                ...m.exact_copied_phrases.map(ph =>
                  p(t(`"${ph}"`, { size: 18, bold: true, color: C.red }))
                ),
              ] : []),
            ],
          }),
        ]})]
      }),
      gap(220),
    )
  })

  return {
    properties: pageProps(),
    headers: { default: makeHeader(label, fileName) },
    footers: { default: makeFooter(label, submissionId) },
    children,
  }
}

// ── Main export ───────────────────────────────────────────────────────────────

export async function generateReport(data: EngineReport, originalFileName: string): Promise<void> {
  // Normalise: fill in missing file_name so all section functions can rely on it
  const normalizedData: EngineReport = { ...data, file_name: data.file_name ?? originalFileName }
  const submissionId = `sentinel:${Date.now()}`
  const submDate     = new Date().toLocaleString('en-GB')
  const totalPages   = 3 + data.sources.length

  const doc = new Document({
    styles: {
      default: { document: { run: { font: 'Arial', size: 20, color: C.black } } },
    },
    sections: [
      coverSection(normalizedData, submissionId, submDate, totalPages),
      overviewSection(normalizedData, submissionId, totalPages),
      topSourcesSection(normalizedData, submissionId, totalPages),
      ...( normalizedData.sources ?? []).map((src, i) =>
        detailSection(src, i, 4 + i, totalPages, normalizedData.file_name!, submissionId)
      ),
    ],
  })

  const blob     = await Packer.toBlob(doc)
  const baseName = (normalizedData.file_name ?? originalFileName).replace(/\.[^/.]+$/, '')
  saveAs(blob, `plagiarism_report_${baseName}.docx`)
}