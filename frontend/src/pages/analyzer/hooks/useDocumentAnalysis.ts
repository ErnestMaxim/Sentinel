import { useState, useCallback } from 'react'
import type { EngineReport } from '../../../types/documents'
import { uploadDocument, analyzeDocument } from '../api'
import { generatePdfReport } from '../../../utils/report'

export type Stage = 'idle' | 'uploading' | 'analyzing' | 'done' | 'error'

export interface DocInfo {
  filename:       string
  processingTime: number | null
  documentId:     number
}

export interface AnalysisState {
  file:         File | null
  dragging:     boolean
  stage:        Stage
  pipeStep:     number
  report:       EngineReport | null
  docInfo:      DocInfo | null
  errorMsg:     string
  isRunning:    boolean
  acceptFile:   (f: File) => void
  setDragging:  (v: boolean) => void
  analyze:      () => Promise<void>
  reset:        () => void
}

const PIPE_STEPS = 5

export function useDocumentAnalysis(): AnalysisState {
  const [file,     setFile]     = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const [stage,    setStage]    = useState<Stage>('idle')
  const [pipeStep, setPipeStep] = useState(0)
  const [report,   setReport]   = useState<EngineReport | null>(null)
  const [docInfo,  setDocInfo]  = useState<DocInfo | null>(null)
  const [errorMsg, setErrorMsg] = useState('')

  const acceptFile = useCallback((f: File) => {
    const allowed = ['.pdf', '.docx', '.txt']
    if (!allowed.some(ext => f.name.endsWith(ext))) {
      setErrorMsg('Only PDF, DOCX, or TXT files are supported.')
      setStage('error')
      return
    }
    setFile(f); setStage('idle'); setReport(null); setErrorMsg('')
  }, [])

  const reset = useCallback(() => {
    setStage('idle'); setReport(null); setFile(null); setErrorMsg('')
  }, [])

  const animatePipeline = async () => {
    for (let i = 1; i <= PIPE_STEPS; i++) {
      await new Promise(r => setTimeout(r, 1100 + Math.random() * 700))
      setPipeStep(i)
    }
  }

  const analyze = useCallback(async () => {
    if (!file) return
    setReport(null); setErrorMsg(''); setPipeStep(0)

    try {
      setStage('uploading')
      const uploaded = await uploadDocument(file)

      setStage('analyzing')
      const [analyzed] = await Promise.all([
        analyzeDocument(uploaded.id),
        animatePipeline(),
      ])

      if (!analyzed.report?.report_data) throw new Error('Engine returned no report data.')

      // Auto-download PDF
      await generatePdfReport(analyzed.report.report_data, analyzed.filename, 'all')

      setReport(analyzed.report.report_data)
      setDocInfo({
        filename:       analyzed.filename,
        processingTime: analyzed.report.processing_time_seconds ?? null,
        documentId:     analyzed.id,
      })
      setStage('done')

    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : 'Something went wrong.')
      setStage('error')
    }
  }, [file])

  return {
    file, dragging, stage, pipeStep, report, docInfo, errorMsg,
    isRunning: stage === 'uploading' || stage === 'analyzing',
    acceptFile, setDragging, analyze, reset,
  }
}
