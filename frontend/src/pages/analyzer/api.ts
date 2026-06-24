import type {UserResponseDto} from '../../api/dto/auth.dto'
import type { DocumentDto } from '../../api/dto/documents.dto'
import { mapDocument }  from '../../api/mappers/documents.mapper'
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

export async function analyzeDocument(docId: number, force = false): Promise<HistoryDocument> {
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
    if (res.status === 504) throw new Error('Analysis timed out. The document might be too long — try a shorter file.')
    if (res.status >= 500)  throw new Error('Something went wrong on the server during analysis. Try again shortly.')
    throw new Error(detail ?? 'Analysis failed. Please try again.')
  }

  const dto: DocumentDto = await res.json()
  return mapDocument(dto)
}

/** Re-analyze a previously analyzed document, bypassing the cache. */
export async function reanalyzeDocument(docId: number): Promise<HistoryDocument> {
  return analyzeDocument(docId, true)
}