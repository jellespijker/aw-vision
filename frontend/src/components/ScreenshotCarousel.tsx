import React, { useState, useEffect } from 'react'
import {
  ChevronLeft,
  ChevronRight,
  Archive,
  User,
  FileText,
  RefreshCw,
  Cpu,
  Maximize2
} from 'lucide-react'
import { HistoryRecord, Project } from '../types'

interface ScreenshotCarouselProps {
  historyRecords: HistoryRecord[]
  projectsList: Project[]
  handleUpdateLabel: (recordId: string, projectNumber: string | null) => void
  handleForceProcess: (fileId: string) => Promise<HistoryRecord | null>
  handleReprocessSnapshots: (options: { ids?: string[]; reprocessOcr?: boolean }) => Promise<boolean>
  processingIds: string[]
  logs: Record<string, string[]>
  formatTimestamp: (ts: number) => string
  API_BASE: string
  openImageLightbox: (rec: HistoryRecord) => void
}

export const ScreenshotCarousel: React.FC<ScreenshotCarouselProps> = ({
  historyRecords,
  projectsList,
  handleUpdateLabel,
  handleForceProcess,
  handleReprocessSnapshots,
  processingIds,
  logs,
  formatTimestamp,
  API_BASE,
  openImageLightbox
}) => {
  const [activeIndex, setActiveIndex] = useState<number>(0)
  const [viewFull, setViewFull] = useState<boolean>(false)
  const [ocrExpanded, setOcrExpanded] = useState<boolean>(false)
  const [logsExpanded, setLogsExpanded] = useState<boolean>(false)

  // Reset active index when historyRecords updates (like new searches)
  useEffect(() => {
    setActiveIndex(0)
  }, [historyRecords])

  if (historyRecords.length === 0) return null

  const activeRecord = historyRecords[activeIndex]
  const isProcessing = processingIds.includes(activeRecord.id)
  const currentLogs = logs[activeRecord.id] || []

  const handlePrev = () => {
    setActiveIndex((prev) => (prev === 0 ? historyRecords.length - 1 : prev - 1))
  }

  const handleNext = () => {
    setActiveIndex((prev) => (prev === historyRecords.length - 1 ? 0 : prev + 1))
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 font-sans">
      {/* Left Pane: Interactive Image Stage (7 Columns) */}
      <div className="lg:col-span-7 flex flex-col bg-surface-container-lowest rounded-lg border border-surface-container-high overflow-hidden select-none">
        {/* Stage Header */}
        <div className="p-4 bg-surface-container-low border-b border-surface-container-high flex items-center justify-between font-messina text-action-md">
          <span className="text-text-secondary font-medium font-mono text-[11px]">
            Capture {activeIndex + 1} of {historyRecords.length}
          </span>
          <span className="bg-black/70 text-white text-[10px] font-mono px-2 py-0.5 rounded">
            {formatTimestamp(activeRecord.timestamp)}
          </span>
        </div>

        {/* Sliding Stage Viewport */}
        <div className="relative h-[320px] md:h-[400px] bg-surface-container flex items-center justify-center group overflow-hidden">
          {activeRecord.image_filename ? (
            <>
              {/* Active / Full Toggle switch overlay */}
              <div className="absolute top-4 left-4 z-10 flex gap-1 bg-surface-container-lowest/95 p-0.5 rounded border border-surface-container-high text-[9px] font-semibold font-messina">
                <button
                  type="button"
                  onClick={() => setViewFull(false)}
                  className={`px-1.5 py-0.5 rounded-sm transition-colors cursor-pointer ${
                    !viewFull ? 'bg-primary text-on-primary font-bold' : 'text-text-secondary hover:text-neutral-dark'
                  }`}
                >
                  Active Window
                </button>
                <button
                  type="button"
                  onClick={() => setViewFull(true)}
                  className={`px-1.5 py-0.5 rounded-sm transition-colors cursor-pointer ${
                    viewFull ? 'bg-primary text-on-primary font-bold' : 'text-text-secondary hover:text-neutral-dark'
                  }`}
                >
                  Full Desktop
                </button>
              </div>

              {/* Slide image with lightbox trigger on click */}
              <img
                src={`${API_BASE}/api/screenshots/${
                  viewFull ? activeRecord.image_filename.replace('.png', '_full.png') : activeRecord.image_filename
                }`}
                className="w-full h-full object-contain cursor-pointer select-all"
                alt="Active desktop capture slide"
                onClick={() => openImageLightbox(activeRecord)}
              />

              {/* Glass zoom indicator overlay */}
              <div
                className="absolute inset-0 bg-inverse-surface/10 opacity-0 group-hover:opacity-100 flex items-center justify-center transition-opacity cursor-pointer"
                onClick={() => openImageLightbox(activeRecord)}
              >
                <div className="w-10 h-10 bg-surface-container-lowest border border-surface-container-high rounded-full flex items-center justify-center shadow-none">
                  <Maximize2 className="w-4 h-4 text-primary" />
                </div>
              </div>
            </>
          ) : (
            <div className="absolute inset-0 bg-surface-container-low flex flex-col items-center justify-center p-4 text-center">
              <Archive className="w-12 h-12 text-disabled mb-2 opacity-50" />
              <span className="text-[10px] font-semibold text-text-secondary uppercase tracking-wider font-messina">
                Archived Metadata
              </span>
              <span className="text-[11px] text-text-secondary mt-1 max-w-xs">
                Screenshot purged from host disk (14-day storage lifecycle thresholds reached)
              </span>
            </div>
          )}

          {/* Nav Chevrons overlay */}
          <button
            onClick={handlePrev}
            className="absolute left-4 top-1/2 -translate-y-1/2 z-10 w-9 h-9 rounded border border-surface-container-high bg-surface-container-lowest/95 text-text-secondary hover:text-neutral-dark hover:bg-surface-container-low flex items-center justify-center transition-colors cursor-pointer"
            title="Previous Screenshot"
          >
            <ChevronLeft className="w-5 h-5" />
          </button>
          <button
            onClick={handleNext}
            className="absolute right-4 top-1/2 -translate-y-1/2 z-10 w-9 h-9 rounded border border-surface-container-high bg-surface-container-lowest/95 text-text-secondary hover:text-neutral-dark hover:bg-surface-container-low flex items-center justify-center transition-colors cursor-pointer"
            title="Next Screenshot"
          >
            <ChevronRight className="w-5 h-5" />
          </button>
        </div>

        {/* Thumbnail Navigation Strip */}
        <div className="p-3 bg-surface-container-low border-t border-surface-container-high overflow-x-auto flex gap-2 items-center justify-center">
          {historyRecords.map((rec, idx) => {
            const isSelected = idx === activeIndex
            return (
              <button
                key={rec.id}
                onClick={() => setActiveIndex(idx)}
                className={`relative w-12 h-8 rounded border overflow-hidden flex-shrink-0 transition-all cursor-pointer ${
                  isSelected ? 'border-primary ring-1 ring-primary' : 'border-surface-container-high hover:border-primary'
                }`}
              >
                {rec.image_filename ? (
                  <img
                    src={`${API_BASE}/api/screenshots/${rec.image_filename}`}
                    className="w-full h-full object-cover"
                    alt={`Thumbnail preview ${idx}`}
                  />
                ) : (
                  <div className="w-full h-full bg-surface-container flex items-center justify-center text-[8px] font-semibold text-text-secondary">
                    ARC
                  </div>
                )}
              </button>
            )
          })}
        </div>
      </div>

      {/* Right Pane: Contextual Details Drawer (5 Columns) */}
      <div className="lg:col-span-5 flex flex-col bg-surface-container-lowest rounded-lg border border-surface-container-high p-5 space-y-4">
        {/* Verification label selection section */}
        <div className="flex items-center justify-between gap-3 text-technical-sm font-mono pb-3 border-b border-surface-container-high">
          <div className="flex items-center gap-2">
            {activeRecord.is_processed ? (
              <div className="flex items-center gap-1.5 bg-surface-container-low border border-surface-container-high px-2.5 py-1 rounded font-messina text-action-md">
                {activeRecord.human_labeled && (
                  <div className="flex items-center gap-1 text-primary font-bold text-[10px] uppercase tracking-wider pr-1.5 border-r border-surface-container-high">
                    <User className="w-3.5 h-3.5" />
                    <span>Verified</span>
                  </div>
                )}
                <select
                  value={activeRecord.project_number || 'None'}
                  onChange={(e) => {
                    const val = e.target.value
                    handleUpdateLabel(activeRecord.id, val === 'None' ? null : val)
                  }}
                  className="bg-transparent text-[11px] font-semibold text-neutral-dark outline-none cursor-pointer border-0 p-0 pr-1 select-none"
                  aria-label="Select active project classification"
                >
                  <option value="None">Unclassified</option>
                  {projectsList
                    .filter((p) => p.project_number !== 'Unclassified')
                    .map((proj) => (
                      <option key={proj.project_number} value={proj.project_number}>
                        {proj.project_number}
                      </option>
                    ))}
                </select>
              </div>
            ) : (
              <span className="bg-surface-container-low text-text-secondary font-semibold px-2.5 py-1 rounded border border-surface-container-high font-sans text-body-sm">
                Pending classification
              </span>
            )}
            <span className="bg-surface-container-low text-text-secondary font-semibold px-2.5 py-1 rounded border border-surface-container-high font-sans text-body-sm max-w-[150px] truncate">
              {activeRecord.app_name}
            </span>
          </div>

          {activeRecord.is_afk && (
            <span className="px-2 h-6 flex items-center bg-danger-surface text-error rounded-full text-indicator-bold border border-danger-primary/20 dark:bg-danger-primary/10 dark:text-danger-primary dark:border-danger-primary/15 font-messina text-[10px]">
              AFK
            </span>
          )}
        </div>

        {/* Heading window title and vision description */}
        <div className="space-y-2">
          <h4 className="font-semibold text-headline-sm text-neutral-dark leading-tight" title={activeRecord.window_title}>
            {activeRecord.window_title}
          </h4>
          <p className="text-text-secondary text-body-sm leading-relaxed">{activeRecord.description}</p>
        </div>

        {/* Collapsible monospaced OCR text panel */}
        {activeRecord.is_processed && activeRecord.ocr_text && (
          <div className="bg-surface-container-low p-3 rounded border border-surface-container-high">
            <button
              onClick={() => setOcrExpanded(!ocrExpanded)}
              className="w-full text-left flex items-center justify-between text-[10px] font-semibold uppercase tracking-wider text-text-secondary font-messina cursor-pointer select-none"
            >
              <span className="flex items-center gap-1.5">
                <FileText className="w-3.5 h-3.5 text-primary" /> Extracted OCR Text
              </span>
              <span className="text-primary">{ocrExpanded ? 'Collapse' : 'Expand'}</span>
            </button>
            <div
              className={`transition-all duration-200 overflow-hidden ${
                ocrExpanded ? 'max-h-48 mt-2 overflow-y-auto' : 'max-h-0'
              }`}
            >
              <pre className="text-technical-sm font-mono text-neutral-dark whitespace-pre-wrap select-all leading-normal border border-surface-container p-2 rounded bg-surface-container-lowest text-left block">
                {activeRecord.ocr_text}
              </pre>
            </div>
          </div>
        )}

        {/* Tag badges */}
        {activeRecord.is_processed && activeRecord.tags && activeRecord.tags.length > 0 && (
          <div className="flex flex-wrap gap-1 pt-1">
            {activeRecord.tags.map((tag) => (
              <span
                key={tag}
                className="text-[10px] font-semibold bg-accent-surface text-primary border border-surface-container px-1.5 py-0.5 rounded font-mono"
              >
                #{tag}
              </span>
            ))}
          </div>
        )}

        {/* Re-indexing triggers and consoles */}
        <div className="pt-2 border-t border-surface-container">
          {activeRecord.is_processed ? (
            <button
              type="button"
              onClick={() => handleReprocessSnapshots({ ids: [activeRecord.id], reprocessOcr: false })}
              disabled={isProcessing}
              className="w-full bg-inverse-surface hover:opacity-90 text-inverse-on-surface text-action-md font-semibold h-10 rounded border border-inverse-surface transition-all flex items-center justify-center gap-2 cursor-pointer"
            >
              <RefreshCw className={`w-4 h-4 ${isProcessing ? 'animate-spin' : ''}`} />
              {isProcessing ? 'Reprocessing...' : 'Reprocess Snapshot (OCR-cached)'}
            </button>
          ) : (
            <button
              type="button"
              onClick={async () => {
                await handleForceProcess(activeRecord.id)
              }}
              disabled={isProcessing}
              className="w-full bg-primary hover:bg-primary-container text-on-primary text-action-md font-semibold h-10 rounded border border-primary transition-colors flex items-center justify-center gap-2 cursor-pointer"
            >
              {isProcessing ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Cpu className="w-4 h-4" />}
              {isProcessing ? 'Processing Screenshot...' : 'Process Screenshot'}
            </button>
          )}

          {/* Logs terminal block */}
          {currentLogs.length > 0 && (
            <div className="bg-surface-container-low p-3 rounded border border-surface-container-high space-y-2 mt-3 text-left">
              <button
                onClick={() => setLogsExpanded(!logsExpanded)}
                className="w-full text-left flex items-center justify-between text-[10px] font-semibold uppercase tracking-wider text-text-secondary font-messina cursor-pointer select-none"
              >
                <span className="flex items-center gap-1.5">
                  <FileText className="w-3.5 h-3.5 text-primary" /> Reprocessing logs
                </span>
                <span className="text-primary">{logsExpanded ? 'Hide' : 'Show'}</span>
              </button>
              <div
                className={`transition-all duration-200 overflow-hidden ${
                  logsExpanded ? 'max-h-[140px] overflow-y-auto mt-2' : 'max-h-0'
                }`}
              >
                <div className="bg-surface-container-low border border-surface-container text-text-secondary font-mono text-[10px] p-2 rounded space-y-0.5 select-all leading-normal">
                  {currentLogs.map((line, idx) => (
                    <div key={idx} className="break-all">
                      {line}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
