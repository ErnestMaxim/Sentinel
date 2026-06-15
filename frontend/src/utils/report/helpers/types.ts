// ── types.ts ──────────────────────────────────────────────────────────────────
// All shared TypeScript interfaces and union types for the PDF report system.
// No imports — this file is dependency-free.

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
  file_name?:                      string
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
    timing?: { total_s: number; [key: string]: number }
  }
  sources: EngineSource[]
}

export type ReportFilter = 'all' | 'exact' | 'paraphrase'