// ── Analyzer page API ──────────────────────────────────────────────────────────
// Handles document upload + analysis. Maps raw DTOs → domain types.

import type {UserResponseDto} from '../../api/dto/auth.dto'
import type { DocumentDto } from '../../api/dto/documents.dto'
import { mapDocument }  from '../../api/mappers/documents.mapper'
import type { HistoryDocument } from '../../types/documents'

const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api'

function authHeaders(token: string | null): HeadersInit {
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function resolveUserId(token: string | null): Promise<number> {
  const res = await fetch(`${API}/auth/me`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Not authenticated')
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
    throw new Error(detail ?? 'Upload failed')
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
    throw new Error(detail ?? 'Analysis failed')
  }
  const dto: DocumentDto = await res.json()
  return mapDocument(dto)
}

/** Re-analyze a previously analyzed document, bypassing the cache. */
export async function reanalyzeDocument(docId: number): Promise<HistoryDocument> {
  return analyzeDocument(docId, true)
}
