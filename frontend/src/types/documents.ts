// ── Shared document & report types ────────────────────────────────────────────
export interface EngineMatch {
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
  file_name:                       string
  global_plagiarism_score_percent: number
  total_suspicious_sources:        number
  total_reported_sources:          number
  full_text?:                      string
  display_text?:                   string
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

export type DocumentStatus = 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED'

export interface DocumentReport {
  id:                      number
  global_score:            number
  report_data:             EngineReport
  processing_time_seconds: number | null
  similarity_threshold:    number
  created_at:              string
}

export interface HistoryDocument {
  id:          number
  filename:    string
  status:      DocumentStatus
  word_count:  number | null
  uploaded_at: string
  report?:     DocumentReport | null
}
