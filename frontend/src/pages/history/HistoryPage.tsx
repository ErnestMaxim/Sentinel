import { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  useReactTable,
  getCoreRowModel,
  getPaginationRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  createColumnHelper,
  flexRender,
  type SortingState,
  type ColumnMeta,
} from '@tanstack/react-table'
import { formatDate, formatDateTime } from '../../utils/format'
import type { HistoryDocument } from '../../types/documents'
import { fetchDocuments, reanalyzeDocument } from './api'
import { scoreColorClass } from './utils'
import StatusCell  from './components/StatusCell'
import ReportModal  from './components/ReportModal'
import styles from './HistoryPage.module.css'
import { REPORT_STORAGE_KEY, type StoredReport } from '../report/ReportPage'

// ── Types ────────────────────────────────────────────────────────────────────
declare module '@tanstack/react-table' {
  interface ColumnMeta<TData, TValue> {
    align?: 'left' | 'right' | 'center'
  }
}

// ── Sort indicator ───────────────────────────────────────────────────────────

function SortIcon({ sorted }: { sorted: false | 'asc' | 'desc' }) {
  if (sorted === 'asc') return (
    <svg className={styles.sortIcon} width="9" height="9" viewBox="0 0 9 9" fill="currentColor">
      <path d="M4.5 1.5L8 7H1L4.5 1.5Z"/>
    </svg>
  )
  if (sorted === 'desc') return (
    <svg className={styles.sortIcon} width="9" height="9" viewBox="0 0 9 9" fill="currentColor">
      <path d="M4.5 7.5L1 2H8L4.5 7.5Z"/>
    </svg>
  )
  return (
    <svg className={`${styles.sortIcon} ${styles.sortIconNeutral}`} width="9" height="12" viewBox="0 0 9 12" fill="currentColor">
      <path d="M4.5 1L7.5 4.5H1.5L4.5 1Z" opacity="0.35"/>
      <path d="M4.5 11L1.5 7.5H7.5L4.5 11Z" opacity="0.35"/>
    </svg>
  )
}

// ── Constants ────────────────────────────────────────────────────────────────

const PAGE_SIZE  = 10
const colHelper  = createColumnHelper<HistoryDocument>()

// ── Page component ───────────────────────────────────────────────────────────

export default function HistoryPage() {
  "use no memo"

  const navigate = useNavigate()

  const [docs,          setDocs]          = useState<HistoryDocument[]>([])
  const [loading,       setLoading]       = useState(true)
  const [error,         setError]         = useState<string | null>(null)
  const [globalFilter,  setGlobalFilter]  = useState('')
  const [sorting,       setSorting]       = useState<SortingState>([{ id: 'submitted', desc: true }])
  const [selected,      setSelected]      = useState<HistoryDocument | null>(null)
  const [reanalyzingId, setReanalyzingId] = useState<number | null>(null)

  useEffect(() => {
    fetchDocuments()
      .then(setDocs)
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load history'))
      .finally(() => setLoading(false))
  }, [])

  // ── Handlers ──────────────────────────────────────────────────────────────

  function openReport(e: React.MouseEvent, doc: HistoryDocument) {
    e.stopPropagation()
    if (!doc.report?.report_data) return
    const stored: StoredReport = {
      report:     doc.report.report_data,
      filename:   doc.filename,
      date:       formatDateTime(doc.report.created_at),
      documentId: doc.id,
    }
    sessionStorage.setItem(REPORT_STORAGE_KEY, JSON.stringify(stored))
    navigate('/report')
  }

  function downloadReport(e: React.MouseEvent, doc: HistoryDocument) {
    e.stopPropagation()
    if (!doc.report?.report_data) return
    const stored: StoredReport = {
      report:     doc.report.report_data,
      filename:   doc.filename,
      date:       formatDateTime(doc.report.created_at),
      documentId: doc.id,
      autoPrint:  true,
    }
    sessionStorage.setItem(REPORT_STORAGE_KEY, JSON.stringify(stored))
    navigate('/report')
  }

  async function handleReanalyze(e: React.MouseEvent, doc: HistoryDocument) {
    e.stopPropagation()
    setReanalyzingId(doc.id)
    try {
      const updated = await reanalyzeDocument(doc.id)
      setDocs(prev => prev.map(d => d.id === doc.id ? updated : d))
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Re-analysis failed')
    } finally {
      setReanalyzingId(null)
    }
  }

  // ── Column definitions ────────────────────────────────────────────────────
  const columns = [
    colHelper.accessor('filename', {
      id:       'document',
      header:   'Document',
      filterFn: 'includesString',
      sortingFn:'alphanumeric',
      meta:     { align: 'left' },
      cell: ({ row }) => {
        const doc = row.original
        return (
          <div className={styles.fileCell}>
            <span className={styles.fileIconWrap}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
              </svg>
            </span>
            <div className={styles.fileInfo}>
              <span className={styles.fileName}>{doc.filename}</span>
              <span className={styles.fileWords}>
                {doc.word_count != null ? `${doc.word_count.toLocaleString()} words` : '—'}
              </span>
            </div>
          </div>
        )
      },
    }),

    colHelper.accessor(row => row.report?.global_score ?? null, {
      id:                'similarity',
      header:            'Similarity',
      enableGlobalFilter: false,
      sortingFn:         'basic',
      meta:              { align: 'right' },
      cell: ({ getValue }) => {
        const score = getValue()
        return (
          <span className={score !== null ? scoreColorClass(score) : styles.scoreNone}>
            {score !== null ? `${score.toFixed(1)}%` : '—'}
          </span>
        )
      },
    }),

    colHelper.accessor('status', {
      id:                'status',
      header:            'Status',
      enableGlobalFilter: false,
      enableSorting:     false,
      meta:              { align: 'right' },
      cell: ({ getValue }) => <StatusCell status={getValue()} />,
    }),

    colHelper.accessor('uploaded_at', {
      id:                'submitted',
      header:            'Submitted',
      enableGlobalFilter: false,
      sortingFn:         'alphanumeric',
      meta:              { align: 'right' },
      cell: ({ getValue }) => (
        <span className={styles.dateText}>{formatDate(getValue())}</span>
      ),
    }),

    colHelper.display({
      id:           'action',
      header:       'Action',
      enableSorting: false,
      meta:          { align: 'right' },
      cell: ({ row }) => {
        const doc           = row.original
        const hasReport     = doc.status === 'COMPLETED' && !!doc.report?.report_data
        const isReanalyzing = reanalyzingId === doc.id
        const isCompleted   = doc.status === 'COMPLETED'
        return (
          <div className={styles.actionCell}>
            {isCompleted && (
              <button
                type="button"
                className={styles.reanalyzeBtn}
                onClick={e => handleReanalyze(e, doc)}
                disabled={isReanalyzing}
              >
                {isReanalyzing
                  ? <><span className={styles.spinner} />Running…</>
                  : <>↺ Re-analyze</>}
              </button>
            )}
            {hasReport && (
              <>
                <button type="button" className={styles.viewBtn} onClick={e => openReport(e, doc)}>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                    <circle cx="12" cy="12" r="3"/>
                  </svg>
                  View
                </button>
                <button type="button" className={styles.downloadBtn} onClick={e => downloadReport(e, doc)}>
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                    <polyline points="7 10 12 15 17 10"/>
                    <line x1="12" y1="15" x2="12" y2="3"/>
                  </svg>
                  PDF
                </button>
              </>
            )}
          </div>
        )
      },
    }),
  ]

  // ── Table instance ─────────────────────────────────────────────────────────

  const table = useReactTable({
    data:    docs,
    columns,
    state:   { globalFilter, sorting },
    onGlobalFilterChange: setGlobalFilter,
    onSortingChange:      setSorting,
    globalFilterFn:        'includesString',
    getCoreRowModel:       getCoreRowModel(),
    getFilteredRowModel:   getFilteredRowModel(),
    getSortedRowModel:     getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: {
      pagination: { pageSize: PAGE_SIZE, pageIndex: 0 },
    },
  })

  // ── Derived values ─────────────────────────────────────────────────────────

  const { pagination }  = table.getState()
  const filteredCount   = table.getFilteredRowModel().rows.length
  const totalPages      = table.getPageCount()
  const currentPage     = pagination.pageIndex + 1
  const firstRow        = pagination.pageIndex * pagination.pageSize + 1
  const lastRow         = Math.min(firstRow + pagination.pageSize - 1, filteredCount)

  const completedDocs   = docs.filter(d => d.status === 'COMPLETED')
  const avgScore        = completedDocs.length
    ? completedDocs.reduce((s, d) => s + (d.report?.global_score ?? 0), 0) / completedDocs.length
    : 0

  // sliding page-button window
  const pageBtns: number[] = []
  for (let i = Math.max(1, currentPage - 2); i <= Math.min(totalPages, currentPage + 2); i++) {
    pageBtns.push(i)
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className={styles.page}>
      <main className={styles.main}>

        {/* ── Header ── */}
        <div className={styles.header}>
          <div className={styles.headerTop}>
            <div className={styles.titleRow}>
              <h1 className={styles.title}>History</h1>
              {!loading && !error && (
                <span className={styles.titleMeta}>
                  <span>{docs.length}</span> submissions
                  {completedDocs.length > 0 && (
                    <> · avg <span>{avgScore.toFixed(1)}%</span> similarity</>
                  )}
                </span>
              )}
            </div>

            <label className={styles.searchBar}>
              <span className={styles.searchIcon}>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
                  stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="11" cy="11" r="8"/>
                  <line x1="21" y1="21" x2="16.65" y2="16.65"/>
                </svg>
              </span>
              <input
                className={styles.searchInput}
                type="text"
                placeholder="Search by filename…"
                value={globalFilter}
                onChange={e => { setGlobalFilter(e.target.value); table.setPageIndex(0) }}
              />
              {globalFilter && (
                <button
                  className={styles.searchClear}
                  type="button"
                  aria-label="Clear search"
                  onClick={() => { setGlobalFilter(''); table.setPageIndex(0) }}
                >
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                    <line x1="18" y1="6" x2="6" y2="18"/>
                    <line x1="6" y1="6" x2="18" y2="18"/>
                  </svg>
                </button>
              )}
            </label>
          </div>
        </div>

        {error && <div className={styles.errorBanner}>⚠ {error}</div>}

        {/* ── Table ── */}
        <div className={styles.tableWrap}>
          <table className={styles.table}>

            {/* Column widths */}
            <colgroup>
              <col />                          {/* Document — flexible */}
              <col style={{ width: '110px' }} /> {/* Similarity */}
              <col style={{ width: '100px' }} /> {/* Status */}
              <col style={{ width: '130px' }} /> {/* Submitted */}
              <col style={{ width: '240px' }} /> {/* Action */}
            </colgroup>

            <thead className={styles.thead}>
              {table.getHeaderGroups().map(hg => (
                <tr key={hg.id}>
                  {hg.headers.map(header => {
                    const canSort = header.column.getCanSort()
                    const sorted  = header.column.getIsSorted()
                    const align   = (header.column.columnDef.meta as ColumnMeta<HistoryDocument, unknown>)?.align ?? 'left'
                    return (
                      <th
                        key={header.id}
                        className={[
                          styles.th,
                          canSort  ? styles.thSortable : '',
                          sorted   ? styles.thSorted   : '',
                          align === 'right'  ? styles.thRight  : '',
                          align === 'center' ? styles.thCenter : '',
                        ].filter(Boolean).join(' ')}
                        onClick={header.column.getToggleSortingHandler()}
                      >
                        <span className={styles.thInner}>
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          {canSort && <SortIcon sorted={sorted} />}
                        </span>
                      </th>
                    )
                  })}
                </tr>
              ))}
            </thead>

            <tbody className={styles.tbody}>
              {loading && (
                // Skeleton rows
                Array.from({ length: PAGE_SIZE }).map((_, i) => (
                  <tr key={i} className={styles.skeletonTr}>
                    <td className={styles.td}>
                      <div className={styles.skeletonBlock}>
                        <div className={styles.skeletonLine} style={{ width: `${50 + (i % 4) * 10}%` }} />
                        <div className={styles.skeletonLine} style={{ width: '80px', marginTop: '6px', height: '8px', opacity: 0.5 }} />
                      </div>
                    </td>
                    {[80, 70, 90, 160].map((w, j) => (
                      <td key={j} className={`${styles.td} ${styles.tdRight}`}>
                        <div className={styles.skeletonLine} style={{ width: `${w}%`, marginLeft: 'auto' }} />
                      </td>
                    ))}
                  </tr>
                ))
              )}

              {!loading && !error && filteredCount === 0 && (
                <tr>
                  <td colSpan={5} className={styles.td}>
                    <div className={styles.emptyState}>
                      <p className={styles.emptyTitle}>
                        {globalFilter ? `No results for "${globalFilter}"` : 'No submissions yet'}
                      </p>
                      <p className={styles.emptyBody}>
                        {globalFilter
                          ? 'Try a different filename.'
                          : 'Upload a document and run an analysis — it will appear here.'}
                      </p>
                      {!globalFilter && (
                        <Link to="/check" className={styles.emptyLink}>Check a document →</Link>
                      )}
                    </div>
                  </td>
                </tr>
              )}

              {!loading && !error && table.getRowModel().rows.map(row => {
                const doc       = row.original
                const hasReport = doc.status === 'COMPLETED' && !!doc.report?.report_data
                return (
                  <tr
                    key={row.id}
                    className={`${styles.tr} ${hasReport ? styles.trClickable : ''}`}
                    onClick={() => hasReport && setSelected(doc)}
                  >
                    {row.getVisibleCells().map(cell => {
                      const align = (cell.column.columnDef.meta as ColumnMeta<HistoryDocument, unknown>)?.align ?? 'left'
                      return (
                        <td
                          key={cell.id}
                          className={[
                            styles.td,
                            align === 'right'  ? styles.tdRight  : '',
                            align === 'center' ? styles.tdCenter : '',
                          ].filter(Boolean).join(' ')}
                        >
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
            </tbody>
          </table>

          {/* ── Pagination ── */}
          {!loading && !error && filteredCount > 0 && (
            <div className={styles.pagination}>
              <span className={styles.pageInfo}>
                {filteredCount > 0 ? `${firstRow}–${lastRow} of ${filteredCount}` : '0 results'}
              </span>

              <div className={styles.pageBtns}>
                <button type="button" className={styles.pageNav} title="First"
                  onClick={() => table.setPageIndex(0)} disabled={!table.getCanPreviousPage()}>«</button>
                <button type="button" className={styles.pageNav} title="Previous"
                  onClick={() => table.previousPage()} disabled={!table.getCanPreviousPage()}>‹</button>

                {pageBtns[0] > 1 && <span className={styles.pageEllipsis}>…</span>}
                {pageBtns.map(n => (
                  <button
                    key={n}
                    type="button"
                    className={`${styles.pageBtn} ${n === currentPage ? styles.pageBtnActive : ''}`}
                    onClick={() => table.setPageIndex(n - 1)}
                  >{n}</button>
                ))}
                {pageBtns[pageBtns.length - 1] < totalPages && <span className={styles.pageEllipsis}>…</span>}

                <button type="button" className={styles.pageNav} title="Next"
                  onClick={() => table.nextPage()} disabled={!table.getCanNextPage()}>›</button>
                <button type="button" className={styles.pageNav} title="Last"
                  onClick={() => table.setPageIndex(totalPages - 1)} disabled={!table.getCanNextPage()}>»</button>
              </div>

              <select
                className={styles.pageSizeSelect}
                aria-label="Rows per page"
                value={pagination.pageSize}
                onChange={e => { table.setPageSize(Number(e.target.value)); table.setPageIndex(0) }}
              >
                {[10, 20, 50].map(n => <option key={n} value={n}>{n} per page</option>)}
              </select>
            </div>
          )}
        </div>

      </main>

      {selected && <ReportModal doc={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}
