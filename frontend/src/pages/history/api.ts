// ── History page API ───────────────────────────────────────────────────────────
// Fetches the user's document list and maps raw DTOs → domain types.

import type { DocumentDto } from '../../api/dto/documents.dto'
import { mapDocument }      from '../../api/mappers/documents.mapper'
import type { HistoryDocument } from '../../types/documents'

const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api'

function authHeaders() {
  const token = localStorage.getItem('access_token')
  return token ? { Authorization: `Bearer ${token}` } : {} as HeadersInit
}

export async function reanalyzeDocument(docId: number): Promise<HistoryDocument> {
  const res = await fetch(`${API}/documents/${docId}/analyze?force=true`, {
    method:  'POST',
    headers: authHeaders(),
  })
  if (!res.ok) {
    const { detail } = await res.json().catch(() => ({})) as { detail?: string }
    throw new Error(detail ?? `Re-analysis failed (${res.status})`)
  }
  const dto: DocumentDto = await res.json()
  return mapDocument(dto)
}

export async function fetchDocuments(): Promise<HistoryDocument[]> {
  const res = await fetch(`${API}/documents/`, {
    headers: authHeaders(),
  })
  if (!res.ok) {
    const { detail } = await res.json().catch(() => ({})) as { detail?: string }
    throw new Error(detail ?? `Server error ${res.status}`)
  }
  const dtos: DocumentDto[] = await res.json()
  return dtos.map(mapDocument)
}
