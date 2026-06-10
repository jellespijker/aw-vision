import React from 'react'
import { X, Archive, User, FileText, RefreshCw, Cpu, Sparkles } from 'lucide-react'
import { HistoryRecord, Project } from '../types'

interface LightboxModalProps {
  isOpen: boolean
  onClose: () => void
  selectedRecord: HistoryRecord | null
  setSelectedRecord: (rec: HistoryRecord) => void
  lightboxViewFull: boolean
  setLightboxViewFull: (val: boolean) => void
  projectsList: Project[]
  handleUpdateLabel: (recordId: string, projectNumber: string | null) => void
  handleForceProcess: (fileId: string) => Promise<HistoryRecord | null>
  handleReprocessSnapshots: (options: { ids?: string[]; reprocessOcr?: boolean }) => Promise<boolean>
  processingIds: string[]
  logs: Record<string, string[]>
  expandedOcrCardId: string | null
  setExpandedOcrCardId: (val: string | null) => void
  formatTimestamp: (ts: number) => string
  API_BASE: string
}

export const LightboxModal: React.FC<LightboxModalProps> = ({
  isOpen,
  onClose,
  selectedRecord,
  setSelectedRecord,
  lightboxViewFull,
  setLightboxViewFull,
  projectsList,
  handleUpdateLabel,
  handleForceProcess,
  handleReprocessSnapshots,
  processingIds,
  logs,
  expandedOcrCardId,
  setExpandedOcrCardId,
  formatTimestamp,
  API_BASE
}) => {
  if (!isOpen || !selectedRecord) return null

  const isProcessing = processingIds.includes(selectedRecord.id)
  const snapshotLogs = logs[selectedRecord.id] || []

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center p-4 font-sans">
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/80" onClick={onClose}></div>

      {/* Modal Container (Strict flat design, Messina action-oriented, IBM Plex typography) */}
      <div className="relative z-10 max-w-4xl w-full bg-surface-container-lowest rounded-lg overflow-hidden border border-surface-container-high flex flex-col shadow-none">
        {/* Close Button */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 z-20 w-8 h-8 rounded border border-surface-container-high bg-surface-container-lowest/90 hover:bg-surface-container-low text-text-secondary hover:text-neutral-dark flex items-center justify-center transition-colors cursor-pointer select-none"
          title="Close Lightbox"
        >
          <X className="w-4 h-4" />
        </button>

        {/* Image Frame with crop mode toggle options */}
        <div className="bg-surface-container flex justify-center items-center p-3 border-b border-surface-container-high h-[380px] md:h-[450px] relative">
          {selectedRecord.image_filename && (
            <div className="absolute top-4 left-4 z-20 flex gap-1 bg-surface-container-lowest/95 p-0.5 rounded border border-surface-container-high text-[10px] font-semibold font-messina select-none">
              <button
                type="button"
                onClick={() => setLightboxViewFull(false)}
                className={`px-2.5 py-1 rounded-sm transition-colors cursor-pointer ${
                  !lightboxViewFull ? 'bg-primary text-white font-bold' : 'text-text-secondary hover:text-neutral-dark'
                }`}
              >
                Active Window Crop
              </button>
              <button
                type="button"
                onClick={() => setLightboxViewFull(true)}
                className={`px-2.5 py-1 rounded-sm transition-colors cursor-pointer ${
                  lightboxViewFull ? 'bg-primary text-white font-bold' : 'text-text-secondary hover:text-neutral-dark'
                }`}
              >
                Full Desktop
              </button>
            </div>
          )}

          {selectedRecord.image_filename ? (
            <img
              src={`${API_BASE}/api/screenshots/${
                lightboxViewFull ? selectedRecord.image_filename.replace('.png', '_full.png') : selectedRecord.image_filename
              }`}
              className="max-w-full max-h-full rounded object-contain select-all"
              alt="Desktop screenshot display"
            />
          ) : (
            <div className="text-center p-8 space-y-3">
              <Archive className="w-16 h-16 text-disabled mx-auto opacity-50" />
              <h3 className="font-semibold text-headline-sm text-neutral-dark">Screenshot Image Archived</h3>
              <p className="text-text-secondary text-body-sm max-w-md mx-auto leading-relaxed">
                This screen capture occurred more than 14 days ago. To preserve disk footprint, the binary image file has
                been cleanly purged from disk, but its analysis descriptions, tags, and semantic indexing vector are
                retained permanently.
              </p>
            </div>
          )}
        </div>

        {/* Text metadata footer content */}
        <div className="p-5 md:p-6 space-y-4 max-h-[300px] overflow-y-auto bg-surface-container-lowest text-neutral-dark">
          <div className="flex flex-wrap items-center justify-between gap-3 text-technical-sm font-mono">
            <div className="flex items-center gap-2">
              {selectedRecord.is_processed ? (
                <div className="flex items-center gap-1.5 bg-surface-container-low border border-surface-container-high px-2.5 py-1 rounded font-messina">
                  {selectedRecord.human_labeled && (
                    <div
                      className="flex items-center gap-1 text-primary font-bold text-[10px] uppercase tracking-wider pr-1.5 border-r border-surface-container-high"
                      title="Manually Verified Project Label"
                    >
                      <User className="w-3.5 h-3.5 text-primary" />
                      <span>Verified</span>
                    </div>
                  )}
                  <select
                    value={selectedRecord.project_number || 'None'}
                    onChange={(e) => {
                      const val = e.target.value
                      handleUpdateLabel(selectedRecord.id, val === 'None' ? null : val)
                    }}
                    className="bg-transparent text-[11px] font-semibold text-neutral-dark outline-none cursor-pointer border-0 p-0 pr-1 select-none"
                    aria-label="Select active project classification for modal"
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
              <span className="bg-surface-container-low text-text-secondary font-semibold px-2.5 py-1 rounded border border-surface-container-high font-sans text-body-sm">
                {selectedRecord.app_name}
              </span>
            </div>
            <span className="text-text-secondary font-medium">{formatTimestamp(selectedRecord.timestamp)}</span>
          </div>

          <div className="space-y-1">
            <h2 className="font-semibold text-headline-sm leading-tight font-sans text-neutral-dark">
              {selectedRecord.window_title}
            </h2>
            <p className="text-text-secondary text-body-sm leading-relaxed">{selectedRecord.description}</p>
          </div>

          {/* Unique Scene Elements & Tools */}
          {selectedRecord.is_processed && selectedRecord.unique_things && (
            <div className="bg-surface-container-low p-4 rounded border border-surface-container-high space-y-2">
              <h3 className="text-[10px] font-semibold uppercase tracking-wider text-text-secondary flex items-center gap-1.5 font-messina">
                <Sparkles className="w-4 h-4 text-primary" /> Unique Scene Elements &amp; Tools
              </h3>
              <div className="bg-surface-container-lowest border border-surface-container p-3 rounded space-y-1.5 max-h-48 overflow-y-auto text-left">
                {selectedRecord.unique_things.split('\n')
                  .map(line => line.replace(/^[-\*\s•\d\.]+\s*/, '').trim())
                  .filter(line => line.length > 0)
                  .map((thing, idx) => (
                    <div key={idx} className="flex items-start gap-2 text-body-sm text-neutral-dark font-medium">
                      <span className="w-1.5 h-1.5 bg-primary rounded-full mt-1.5 flex-shrink-0"></span>
                      <span>{thing}</span>
                    </div>
                  ))}
              </div>
            </div>
          )}

          {/* Collapsible fully parsed OCR text preview (IBM Plex Mono) */}
          {selectedRecord.ocr_text && (
            <div className="bg-surface-container-low p-4 rounded border border-surface-container-high space-y-2">
              <h3 className="text-[10px] font-semibold uppercase tracking-wider text-text-secondary flex items-center gap-1.5 font-messina">
                <FileText className="w-4 h-4 text-primary" /> Fully Parsed Code &amp; Extracted Text (OCR)
              </h3>
              <pre className="text-technical-sm font-mono text-neutral-dark whitespace-pre-wrap select-all max-h-48 overflow-y-auto border border-surface-container p-2 rounded bg-surface-container-lowest leading-normal">
                {selectedRecord.ocr_text}
              </pre>
            </div>
          )}

          {/* Tags list and action buttons */}
          {selectedRecord.is_processed ? (
            <div className="space-y-4">
              {selectedRecord.tags && selectedRecord.tags.length > 0 && (
                <div className="flex flex-wrap gap-1.5 pt-2 border-t border-surface-container">
                  {selectedRecord.tags.map((tag) => (
                    <span
                      key={tag}
                      className="text-technical-sm font-semibold bg-accent-surface border border-surface-container-high text-primary px-2 py-0.5 rounded font-mono"
                    >
                      #{tag}
                    </span>
                  ))}
                </div>
              )}
              <div className="pt-2 border-t border-surface-container">
                <button
                  type="button"
                  onClick={async () => {
                    await handleReprocessSnapshots({ ids: [selectedRecord.id], reprocessOcr: false })
                  }}
                  disabled={isProcessing}
                  className="w-full bg-inverse-surface hover:opacity-90 text-inverse-on-surface text-action-sm font-semibold py-2 px-3 rounded border border-inverse-surface flex items-center justify-center gap-2 transition-all disabled:opacity-50 select-none cursor-pointer font-messina text-action-md"
                  title="Reprocess this snapshot to refresh tags, project guesses, and descriptions"
                >
                  <RefreshCw className={`w-4 h-4 ${isProcessing ? 'animate-spin' : ''}`} />
                  {isProcessing ? 'Reprocessing Snapshot...' : 'Reprocess Snapshot (OCR-cached)'}
                </button>
              </div>
            </div>
          ) : (
            <div className="pt-2 border-t border-surface-container">
              <button
                type="button"
                onClick={async () => {
                  const updated = await handleForceProcess(selectedRecord.id)
                  if (updated) setSelectedRecord(updated)
                }}
                disabled={isProcessing}
                className="w-full bg-primary hover:bg-primary-container text-white text-action-sm font-semibold py-2 px-3 rounded flex items-center justify-center gap-2 transition-colors disabled:opacity-50 select-none cursor-pointer font-messina text-action-md"
              >
                {isProcessing ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Cpu className="w-4 h-4" />}
                {isProcessing ? 'Processing Screenshot...' : 'Process Screenshot Now'}
              </button>
            </div>
          )}

          {/* Step process logs console window snippet */}
          {snapshotLogs.length > 0 && (
            <div className="bg-surface-container-low p-4 rounded border border-surface-container-high space-y-2 mt-3">
              <button
                onClick={() =>
                  setExpandedOcrCardId(
                    expandedOcrCardId === `logs-${selectedRecord.id}` ? null : `logs-${selectedRecord.id}`
                  )
                }
                className="w-full text-left flex items-center justify-between text-[10px] font-semibold uppercase tracking-wider text-text-secondary font-messina cursor-pointer select-none"
              >
                <span className="flex items-center gap-1.5">
                  <FileText className="w-3.5 h-3.5 text-primary" /> Processing Step Logs
                </span>
                <span className="text-primary">{expandedOcrCardId === `logs-${selectedRecord.id}` ? 'Hide Logs' : 'View Logs'}</span>
              </button>
              <div
                className={`transition-all duration-200 overflow-hidden ${
                  expandedOcrCardId === `logs-${selectedRecord.id}` ? 'max-h-48 overflow-y-auto' : 'max-h-0'
                }`}
              >
                <div className="bg-surface-container-low border border-surface-container text-text-secondary font-mono text-[10px] p-3 rounded space-y-0.5 select-all leading-normal text-left">
                  {snapshotLogs.map((line, idx) => (
                    <div key={idx} className="leading-normal break-all">
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
