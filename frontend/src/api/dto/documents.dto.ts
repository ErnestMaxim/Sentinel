// ── Documents DTO ──────────────────────────────────────────────────────────────
// Raw shapes received from the documents API (snake_case, mirrors backend schemas).

// ── Engine report (from AI microservice, relayed by backend) ──────────────────

export interface EngineMatchDto {
  query_chunk_idx:      number
  query_text:           string
  db_chunk_idx:         number
  db_text:              string
  cosine_similarity:    number
  match_percentage:     number
  exact_copied_phrases: string[]
  db_source_type:       string
  severity?:            'identical' | 'highly_similar' | 'paraphrased'
  detection?:           'exact' | 'paraphrase'
}

export interface EngineSourceDto {
  arxiv_id:                    string
  title:                       string
  match_count:                 number
  average_similarity_percent:  number
  has_exact_copies:            boolean
  score_contribution_percent?: number
  matches:                     EngineMatchDto[]
}

export interface EngineReportDto {
  file_name:                       string
  global_plagiarism_score_percent: number
  total_suspicious_sources:        number
  total_reported_sources:          number
  full_text?:                      string   // normalized text (used for matching)
  display_text?:                   string   // original extracted text (used for display)
  document_stats: {
    total_words:           number
    total_chunks_analyzed: number
  }
  analysis_config: {
    threshold_used:   number
    embedding_model:  string
    category_routing: { enabled: boolean; routed_to: string[] | null }
  }
  sources: EngineSourceDto[]
}

// ── Report record (stored in DB, wraps the engine report) ─────────────────────

export interface ReportDto {
  id:                      number
  global_score:            number
  report_data:             EngineReportDto
  processing_time_seconds: number | null
  similarity_threshold:    number
  created_at:              string
}

// ── Document record ───────────────────────────────────────────────────────────

export type DocumentStatusDto = 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED'

export interface DocumentDto {
  id:          number
  filename:    string
  status:      DocumentStatusDto
  word_count:  number | null
  uploaded_at: string
  report?:     ReportDto | null
}

// ── Upload request ────────────────────────────────────────────────────────────
// Sent as multipart/form-data — typed for documentation purposes.

export interface UploadDocumentRequestDto {
  file:    File
  user_id: number
}
