import type { UserResponseDto } from '../../api/dto/auth.dto'
import type { DocumentDto } from '../../api/dto/documents.dto'
import { mapDocument } from '../../api/mappers/documents.mapper'
import type { HistoryDocument } from '../../types/documents'

const API = import.meta.env.VITE_API_URL

function authHeaders(token: string | null): HeadersInit {
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function resolveUserId(token: string | null): Promise<number> {
  if (!token) throw new Error('You need to sign in before checking a document.')
  const res = await fetch(`${API}/auth/me`, { headers: authHeaders(token) })
  if (res.status === 401) throw new Error('Your session has expired. Please sign in again.')
  if (!res.ok) throw new Error('Could not verify your identity. Try refreshing the page.')
  const dto = await res.json() as UserResponseDto
  return dto.id
}

export async function uploadDocument(file: File): Promise<HistoryDocument> {
  const token  = localStorage.getItem('access_token')
  const userId = await resolveUserId(token)

  const form = new FormData()
  form.append('file', file)
  form.append('user_id', String(userId))

  const res = await fetch(`${API}/documents/upload`, {
    method:  'POST',
    headers: authHeaders(token),
    body:    form,
  })

  if (!res.ok) {
    const { detail } = await res.json().catch(() => ({})) as { detail?: string }
    if (res.status === 401) throw new Error('Your session has expired. Please sign in again.')
    if (res.status === 413) throw new Error('File is too large. Maximum allowed size is 20 MB.')
    if (res.status === 415) throw new Error('Unsupported file type. Only PDF, DOCX, and TXT are accepted.')
    if (res.status >= 500)  throw new Error('The server encountered an error while saving your file. Try again in a moment.')
    throw new Error(detail ?? 'Upload failed. Please try again.')
  }

  const dto: DocumentDto = await res.json()
  return mapDocument(dto)
}

/** Kick off analysis — returns immediately with PROCESSING status. */
export async function startAnalysis(docId: number, force = false): Promise<HistoryDocument> {
  const token = localStorage.getItem('access_token')
  const url   = `${API}/documents/${docId}/analyze${force ? '?force=true' : ''}`
  const res   = await fetch(url, {
    method:  'POST',
    headers: authHeaders(token),
  })

  if (!res.ok) {
    const { detail } = await res.json().catch(() => ({})) as { detail?: string }
    if (res.status === 401) throw new Error('Your session has expired. Please sign in again.')
    if (res.status === 404) throw new Error('Document not found. It may have been deleted — try uploading again.')
    if (res.status === 503) throw new Error('The analysis engine is starting up. Wait a few seconds and try again.')
    throw new Error(detail ?? 'Failed to start analysis. Please try again.')
  }

  const dto: DocumentDto = await res.json()
  return mapDocument(dto)
}

/** Poll GET /documents/{id} until COMPLETED or FAILED. */
export async function pollAnalysis(
  docId: number,
  signal?: AbortSignal,
): Promise<HistoryDocument> {
  const token = localStorage.getItem('access_token')
  const INTERVALS = [2000, 3000, 4000, 5000, 6000]
  let attempt = 0

  while (true) {
    if (signal?.aborted) throw new Error('Analysis cancelled.')

    const delay = INTERVALS[Math.min(attempt, INTERVALS.length - 1)]
    await new Promise(r => setTimeout(r, delay))

    if (signal?.aborted) throw new Error('Analysis cancelled.')

    let res: Response
    try {
      res = await fetch(`${API}/documents/${docId}`, {
        headers: authHeaders(token),
      })
    } catch {
      attempt++
      continue
    }

    if (res.status === 401) throw new Error('Your session has expired. Please sign in again.')
    if (res.status === 404) throw new Error('Document not found.')
    if (!res.ok) { attempt++; continue }

    const dto: DocumentDto = await res.json()
    const doc = mapDocument(dto)

    if (doc.status === 'COMPLETED') return doc
    if (doc.status === 'FAILED')    throw new Error('Analysis failed on the server. Please try again.')

    attempt++
  }
}

/** Re-analyze a previously analyzed document, bypassing the cache. */
export async function reanalyzeDocument(docId: number): Promise<HistoryDocument> {
  return startAnalysis(docId, true)
}