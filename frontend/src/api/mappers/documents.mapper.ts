// ── Documents mapper ───────────────────────────────────────────────────────────
// Converts raw API DTOs → internal domain types used by the app.

import type {
  DocumentDto,
  ReportDto,
  EngineReportDto,
  EngineSourceDto,
  EngineMatchDto,
} from '../dto/documents.dto'

import type {
  HistoryDocument,
  DocumentReport,
  EngineReport,
  EngineSource,
  EngineMatch,
} from '../../types/documents'

export function mapEngineMatch(dto: EngineMatchDto): EngineMatch {
  return {
    query_chunk_idx:      dto.query_chunk_idx,
    query_text:           dto.query_text,
    db_chunk_idx:         dto.db_chunk_idx,
    db_text:              dto.db_text,
    cosine_similarity:    dto.cosine_similarity,
    match_percentage:     dto.match_percentage,
    exact_copied_phrases: dto.exact_copied_phrases,
    db_source_type:       dto.db_source_type,
    detection:            dto.detection,
  }
}

export function mapEngineSource(dto: EngineSourceDto): EngineSource {
  return {
    arxiv_id:                   dto.arxiv_id,
    title:                      dto.title,
    match_count:                dto.match_count,
    average_similarity_percent: dto.average_similarity_percent,
    has_exact_copies:           dto.has_exact_copies,
    score_contribution_percent: dto.score_contribution_percent,
    matches:                    dto.matches.map(mapEngineMatch),
  }
}

export function mapEngineReport(dto: EngineReportDto): EngineReport {
  return {
    file_name:                       dto.file_name,
    global_plagiarism_score_percent: dto.global_plagiarism_score_percent,
    total_suspicious_sources:        dto.total_suspicious_sources,
    total_reported_sources:          dto.total_reported_sources,
    full_text:                       dto.full_text,
    display_text:                    dto.display_text,
    document_stats:                  dto.document_stats,
    analysis_config:                 dto.analysis_config,
    sources:                         dto.sources.map(mapEngineSource),
  }
}

export function mapReport(dto: ReportDto): DocumentReport {
  return {
    id:                      dto.id,
    global_score:            dto.global_score,
    report_data:             mapEngineReport(dto.report_data),
    processing_time_seconds: dto.processing_time_seconds,
    similarity_threshold:    dto.similarity_threshold,
    created_at:              dto.created_at,
  }
}

export function mapDocument(dto: DocumentDto): HistoryDocument {
  return {
    id:          dto.id,
    filename:    dto.filename,
    status:      dto.status,
    word_count:  dto.word_count,
    uploaded_at: dto.uploaded_at,
    report:      dto.report ? mapReport(dto.report) : null,
  }
}
