import { createContext, useContext, useState, useRef, type ReactNode } from 'react'
import type { EngineReport } from '../types/documents'
import type { DocInfo, Stage } from '../pages/analyzer/hooks/useDocumentAnalysis'
import { uploadDocument, analyzeDocument } from '../pages/analyzer/api'
import { generatePdfReport } from '../utils/report'

interface AnalysisContextValue {
  file:        File | null
  stage:       Stage
  pipeStep:    number
  report:      EngineReport | null
  docInfo:     DocInfo | null
  errorMsg:    string
  isRunning:   boolean
  acceptFile:  (f: File) => void
  analyze:     () => Promise<void>
  reset:       () => void
}

const AnalysisContext = createContext<AnalysisContextValue | null>(null)

export function useAnalysis() {
  const ctx = useContext(AnalysisContext)
  if (!ctx) throw new Error('useAnalysis must be used inside AnalysisProvider')
  return ctx
}

const PIPE_STEPS = 5

export function AnalysisProvider({ children }: { children: ReactNode }) {
  const [file,     setFile]     = useState<File | null>(null)
  const [stage,    setStage]    = useState<Stage>('idle')
  const [pipeStep, setPipeStep] = useState(0)
  const [report,   setReport]   = useState<EngineReport | null>(null)
  const [docInfo,  setDocInfo]  = useState<DocInfo | null>(null)
  const [errorMsg, setErrorMsg] = useState('')

  // Prevents double-trigger if analyze() is called twice
  const runningRef = useRef(false)

  function acceptFile(f: File) {
    const allowed = ['.pdf', '.docx', '.txt']
    if (!allowed.some(ext => f.name.endsWith(ext))) {
      setErrorMsg('Only PDF, DOCX, or TXT files are supported.')
      setStage('error')
      return
    }
    setFile(f); setStage('idle'); setReport(null); setErrorMsg('')
  }

  function reset() {
    setStage('idle'); setReport(null); setFile(null); setErrorMsg('')
    runningRef.current = false
  }

  async function animatePipeline() {
    for (let i = 1; i <= PIPE_STEPS; i++) {
      await new Promise(r => setTimeout(r, 1100 + Math.random() * 700))
      setPipeStep(i)
    }
  }

  async function analyze() {
    if (!file || runningRef.current) return
    runningRef.current = true
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
    } finally {
      runningRef.current = false
    }
  }

  return (
    <AnalysisContext.Provider value={{
      file, stage, pipeStep, report, docInfo, errorMsg,
      isRunning: stage === 'uploading' || stage === 'analyzing',
      acceptFile, analyze, reset,
    }}>
      {children}
    </AnalysisContext.Provider>
  )
}