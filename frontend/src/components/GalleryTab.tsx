import React, { useState } from 'react'
import {
  Search,
  RefreshCw,
  Cpu,
  Image as ImageIcon,
  LayoutGrid,
  SlidersHorizontal,
  Archive,
  User,
  FileText,
  Maximize2
} from 'lucide-react'
import type { DaemonStatus, HistoryRecord, Project } from '../types'
import { ScreenshotCarousel } from './ScreenshotCarousel'

interface GalleryTabProps {
  status: DaemonStatus | null
  searchQuery: string
  setSearchQuery: (val: string) => void
  loadingHistory: boolean
  fetchHistory: (page: number, queryOverride?: string) => Promise<void>
  clearSearch: () => void
  handleProcessAll: () => void
  bulkProcessing: boolean
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
  currentPage: number
  totalPages: number
  getPageRange: () => number[]
  expandedOcrCardId: string | null
  setExpandedOcrCardId: (val: string | null) => void
  hasMore: boolean
  loadMore: () => Promise<void>
  totalCount: number
}

export const GalleryTab: React.FC<GalleryTabProps> = ({
  status,
  searchQuery,
  setSearchQuery,
  loadingHistory,
  fetchHistory,
  clearSearch,
  handleProcessAll,
  bulkProcessing,
  historyRecords,
  projectsList,
  handleUpdateLabel,
  handleForceProcess,
  handleReprocessSnapshots,
  processingIds,
  logs,
  formatTimestamp,
  API_BASE,
  openImageLightbox,
  currentPage,
  totalPages,
  getPageRange,
  expandedOcrCardId,
  setExpandedOcrCardId,
  hasMore,
  loadMore,
  totalCount
}) => {
  const [viewMode, setViewMode] = useState<'carousel' | 'grid'>('carousel')
  const [cardViewFull, setCardViewFull] = useState<Record<string, boolean>>({})

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    fetchHistory(1)
  }

  return (
    <div className="space-y-6 font-sans">
      {/* Search Header card with layout view toggles */}
      <div className="bg-surface-container-lowest border border-surface-container-high p-4 rounded-lg flex flex-col md:flex-row items-stretch md:items-center gap-4">
        <form onSubmit={handleSearchSubmit} className="flex-1 flex flex-col sm:flex-row items-center gap-3">
          <div className="relative flex-1 w-full">
            <Search className="w-4 h-4 text-text-secondary absolute left-4 top-1/2 -translate-y-1/2" />
            <input
              id="gallery-search"
              name="gallery-search"
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search semantic features (e.g., 'coding in python' or 'purple dashboard text')..."
              className="w-full pl-11 pr-5 h-10 text-body-md rounded bg-surface-container-lowest border border-surface-container-high text-on-surface focus:outline-none focus:border-primary font-sans"
            />
          </div>
          <div className="flex flex-wrap gap-2 w-full sm:w-auto">
            <button
              type="submit"
              disabled={loadingHistory}
              className="flex-1 sm:flex-initial bg-primary hover:bg-primary-container text-on-primary text-action-md font-medium h-10 px-6 rounded flex items-center justify-center gap-2 transition-colors disabled:opacity-50 select-none cursor-pointer font-messina"
            >
              <RefreshCw className={`w-4 h-4 ${loadingHistory ? 'animate-spin' : ''}`} />
              Search
            </button>
            <button
              type="button"
              onClick={clearSearch}
              className="bg-surface-container-low hover:bg-surface-container text-neutral-dark text-action-md font-medium h-10 px-4 rounded border border-surface-container-high transition-colors select-none cursor-pointer font-messina"
            >
              Clear
            </button>
          </div>
        </form>

        <div className="flex gap-2 shrink-0 border-t md:border-t-0 pt-3 md:pt-0 border-surface-container-high items-center justify-between">
          {/* Layout Mode Toggles (Sleek Segmented Switches) */}
          <div className="bg-surface-container-low p-0.5 rounded border border-surface-container-high flex gap-1 font-messina text-action-md select-none">
            <button
              type="button"
              onClick={() => setViewMode('carousel')}
              className={`h-8 px-3 rounded-sm transition-all flex items-center gap-1.5 cursor-pointer ${
                viewMode === 'carousel'
                  ? 'bg-surface-container-lowest text-primary font-semibold border border-surface-container-high'
                  : 'text-text-secondary hover:text-neutral-dark'
              }`}
            >
              <SlidersHorizontal className="w-3.5 h-3.5" />
              <span>Carousel</span>
            </button>
            <button
              type="button"
              onClick={() => setViewMode('grid')}
              className={`h-8 px-3 rounded-sm transition-all flex items-center gap-1.5 cursor-pointer ${
                viewMode === 'grid'
                  ? 'bg-surface-container-lowest text-primary font-semibold border border-surface-container-high'
                  : 'text-text-secondary hover:text-neutral-dark'
              }`}
            >
              <LayoutGrid className="w-3.5 h-3.5" />
              <span>Grid</span>
            </button>
          </div>

          {(status?.pending_queue_size ?? 0) > 0 && (
            <button
              type="button"
              onClick={handleProcessAll}
              disabled={bulkProcessing}
              className="bg-accent-surface hover:bg-surface-container text-primary text-action-md font-medium h-8 px-3 rounded border border-primary/20 transition-all select-none flex items-center gap-1.5 cursor-pointer font-messina ml-2"
            >
              <Cpu className={`w-3.5 h-3.5 ${bulkProcessing ? 'animate-spin' : ''}`} />
              <span>Process ({status?.pending_queue_size})</span>
            </button>
          )}
        </div>
      </div>

      {/* Primary Gallery Stage */}
      {loadingHistory ? (
        <div className="text-center py-20 bg-surface-container-lowest border border-surface-container-high rounded-lg">
          <div className="w-12 h-12 border-4 border-primary border-t-transparent rounded-full animate-spin mx-auto"></div>
          <p className="text-text-secondary text-body-sm mt-4 font-sans">Consulting local LanceDB vector search...</p>
        </div>
      ) : historyRecords.length === 0 ? (
        <div className="text-center py-16 bg-surface-container-lowest rounded-lg border border-surface-container-high max-w-2xl mx-auto space-y-3">
          <ImageIcon className="w-12 h-12 text-outline-variant mx-auto" />
          <h3 className="font-semibold text-headline-sm text-neutral-dark">No screen captures found</h3>
          <p className="text-text-secondary text-body-sm max-w-md mx-auto px-4 leading-relaxed font-sans">
            Capture logs are created every minute while active. Make sure the watcher is active and the bulk processor has
            parsed files.
          </p>
        </div>
      ) : viewMode === 'carousel' ? (
        /* Carousel View Mode Panel */
        <div className="bg-surface-container-lowest border border-surface-container-high p-6 rounded-lg">
          <ScreenshotCarousel
            historyRecords={historyRecords}
            projectsList={projectsList}
            handleUpdateLabel={handleUpdateLabel}
            handleForceProcess={handleForceProcess}
            handleReprocessSnapshots={handleReprocessSnapshots}
            processingIds={processingIds}
            logs={logs}
            formatTimestamp={formatTimestamp}
            API_BASE={API_BASE}
            openImageLightbox={openImageLightbox}
            hasMore={hasMore}
            loadMore={loadMore}
            totalCount={totalCount}
          />
        </div>
      ) : (
        /* Grid View Mode Panels */
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {historyRecords.map((rec) => {
              const recLogs = logs[rec.id] || []
              const isProcessing = processingIds.includes(rec.id)

              return (
                <div
                  key={rec.id}
                  className="flex flex-col bg-surface-container-lowest rounded-lg overflow-hidden border border-surface-container-high transition-all shadow-none text-left"
                >
                  {/* Image Frame Wrapper */}
                  <div
                    className="relative h-48 bg-surface-container flex items-center justify-center overflow-hidden cursor-pointer border-b border-surface-container-high"
                    onClick={() => openImageLightbox(rec)}
                  >
                    {rec.image_filename ? (
                      <>
                        <div
                          className="absolute bottom-2 left-2 z-10 flex gap-1 bg-surface-container-lowest/95 p-0.5 rounded border border-surface-container-high text-[9px] font-semibold font-messina"
                          onClick={(e) => e.stopPropagation()}
                        >
                           <button
                            type="button"
                            onClick={() => setCardViewFull((prev) => ({ ...prev, [rec.id]: false }))}
                            className={`px-1.5 py-0.5 rounded-sm transition-colors cursor-pointer ${
                              !cardViewFull[rec.id] ? 'bg-primary text-on-primary font-bold' : 'text-neutral-dark hover:text-primary font-medium'
                            }`}
                          >
                            Active
                          </button>
                          <button
                            type="button"
                            onClick={() => setCardViewFull((prev) => ({ ...prev, [rec.id]: true }))}
                            className={`px-1.5 py-0.5 rounded-sm transition-colors cursor-pointer ${
                              cardViewFull[rec.id] ? 'bg-primary text-on-primary font-bold' : 'text-neutral-dark hover:text-primary font-medium'
                            }`}
                          >
                            Full
                          </button>
                        </div>

                        <img
                          src={`${API_BASE}/api/screenshots/${
                            cardViewFull[rec.id] ? rec.image_filename.replace('.png', '_full.png') : rec.image_filename
                          }`}
                          className="w-full h-full object-cover"
                          alt="Computer capture"
                          loading="lazy"
                        />
                        <div className="absolute inset-0 bg-inverse-surface/10 opacity-0 hover:opacity-100 flex items-center justify-center transition-opacity">
                          <div className="w-10 h-10 bg-surface-container-lowest border border-surface-container-high rounded-full flex items-center justify-center shadow-none">
                            <Maximize2 className="w-4 h-4 text-primary" />
                          </div>
                        </div>
                      </>
                    ) : (
                      <div className="absolute inset-0 bg-surface-container-low flex flex-col items-center justify-center p-4 text-center">
                        <Archive className="w-10 h-10 text-disabled mb-2 opacity-50" />
                        <span className="text-[10px] font-semibold text-text-secondary uppercase tracking-wider font-messina">
                          Archived Metadata
                        </span>
                        <span className="text-[10px] text-text-secondary mt-1">Screenshot purged</span>
                      </div>
                    )}

                    <span className="absolute bottom-2 right-2 bg-black/70 text-white text-[10px] font-mono px-2 py-0.5 rounded">
                      {formatTimestamp(rec.timestamp)}
                    </span>

                    {rec.is_processed && (
                      <div
                        className="absolute top-2 left-2 z-10 flex items-center gap-1.5 bg-surface-container-lowest/95 border border-surface-container-high px-2 py-1 rounded select-none font-messina"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {rec.human_labeled && (
                          <div className="flex items-center gap-0.5 text-primary font-bold text-[9px] uppercase tracking-wider pr-1.5 border-r border-surface-container-high">
                            <User className="w-3.5 h-3.5" />
                            <span>Verified</span>
                          </div>
                        )}
                        <select
                          value={rec.project_number || 'None'}
                          onChange={(e) => {
                            const val = e.target.value
                            handleUpdateLabel(rec.id, val === 'None' ? null : val)
                          }}
                          className="bg-transparent text-[10px] font-semibold text-neutral-dark outline-none cursor-pointer border-0 p-0 pr-1 select-none"
                          aria-label="Select active project classification for card"
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

                        <button
                          type="button"
                          onClick={() => handleReprocessSnapshots({ ids: [rec.id], reprocessOcr: false })}
                          disabled={isProcessing}
                          className="pl-1.5 border-l border-surface-container-high text-text-secondary hover:text-primary transition-colors cursor-pointer"
                          title="Reprocess snapshot (OCR-cached)"
                        >
                          <RefreshCw className={`w-3 h-3 ${isProcessing ? 'animate-spin text-primary' : ''}`} />
                        </button>
                      </div>
                    )}

                    {rec.distance !== undefined && (
                      <span className="absolute top-2 right-2 bg-secondary text-white text-[9px] font-semibold px-1.5 py-0.5 rounded font-messina">
                        Match: {Math.max(0, Math.round((1 - rec.distance) * 100))}%
                      </span>
                    )}
                  </div>

                  {/* Card Body */}
                  <div className="p-4 flex-1 flex flex-col justify-between space-y-4">
                    <div>
                      <div className="flex items-center gap-2 mb-2">
                        <span className="px-2 h-6 flex items-center bg-surface-container-low border border-surface-container-high rounded text-technical-sm text-text-secondary max-w-[150px] truncate">
                          {rec.app_name}
                        </span>
                        {rec.is_afk && (
                          <span className="px-2 h-6 flex items-center bg-danger-surface text-error rounded-full text-indicator-bold border border-danger-primary/20 dark:bg-danger-primary/10 dark:text-danger-primary dark:border-danger-primary/15 text-[10px] font-messina">
                            AFK
                          </span>
                        )}
                        {!rec.is_processed && (
                          <span className="px-2 h-6 flex items-center bg-warning-light text-on-tertiary-container rounded-full text-indicator-bold border border-attention-yellow/30 dark:bg-attention-yellow/10 dark:text-attention-yellow dark:border-attention-yellow/20 animate-pulse-slow text-[10px] font-messina">
                            Pending
                          </span>
                        )}
                      </div>

                      <h2 className="font-semibold text-headline-sm text-neutral-dark truncate" title={rec.window_title}>
                        {rec.window_title}
                      </h2>

                      <p className="text-text-secondary text-body-sm line-clamp-3 mt-1" title={rec.description}>
                        {rec.description}
                      </p>

                      {/* Unique Scene Elements & Tools Inline Badges */}
                      {rec.is_processed && rec.unique_things && (
                        <div className="flex flex-wrap gap-1 mt-2 mb-1">
                          {rec.unique_things.split('\n')
                            .map(line => line.replace(/^[-\*\s•\d\.]+\s*/, '').trim())
                            .filter(line => line.length > 0)
                            .slice(0, 3)
                            .map((thing, idx) => (
                              <span key={idx} className="text-[10px] font-medium bg-surface-container-low border border-surface-container-high text-text-secondary px-1.5 py-0.5 rounded truncate max-w-[150px]" title={thing}>
                                {thing}
                              </span>
                            ))}
                        </div>
                      )}

                      {rec.is_processed && rec.ocr_text && (
                        <div className="mt-3 bg-surface-container-low p-2.5 rounded border border-surface-container-high">
                          <button
                            type="button"
                            onClick={() => setExpandedOcrCardId(expandedOcrCardId === rec.id ? null : rec.id)}
                            className="w-full text-left flex items-center justify-between text-[10px] font-semibold uppercase tracking-wider text-text-secondary font-messina cursor-pointer select-none"
                          >
                            <span className="flex items-center gap-1.5">
                              <FileText className="w-3.5 h-3.5 text-primary" /> OCR
                            </span>
                            <span className="text-primary">{expandedOcrCardId === rec.id ? 'Collapse' : 'Expand'}</span>
                          </button>
                          <div
                            className={`transition-all duration-200 overflow-hidden ${
                              expandedOcrCardId === rec.id ? 'max-h-48 mt-2 overflow-y-auto' : 'max-h-5 overflow-hidden'
                            }`}
                          >
                            <pre className="text-technical-sm font-mono text-neutral-dark whitespace-pre-wrap leading-normal block pt-1 select-all text-left">
                              {rec.ocr_text}
                            </pre>
                          </div>
                        </div>
                      )}
                    </div>

                    {rec.is_processed ? (
                      <div className="space-y-2 pt-2 border-t border-surface-container">
                        {rec.tags && rec.tags.length > 0 && (
                          <div className="flex flex-wrap gap-1">
                            {rec.tags.map((tag) => (
                              <span
                                key={tag}
                                className="text-[10px] font-semibold bg-accent-surface text-primary border border-surface-container-high px-1.5 py-0.5 rounded font-mono"
                              >
                                #{tag}
                              </span>
                            ))}
                          </div>
                        )}

                        {(isProcessing || recLogs.length > 0) && (
                          <div className="bg-surface-container-low border border-surface-container-high text-text-secondary font-mono text-[10px] p-2 rounded max-h-[120px] overflow-y-auto space-y-0.5 mt-1 select-all text-left">
                            <div className="text-[9px] font-semibold text-text-primary uppercase tracking-wider mb-1 flex items-center justify-between border-b border-surface-container pb-1 font-messina">
                              <span>Terminal logs</span>
                              {isProcessing && <span className="w-1.5 h-1.5 rounded-full bg-success-green animate-ping"></span>}
                            </div>
                            {recLogs.map((line, idx) => (
                              <div key={idx} className="leading-normal break-all">
                                {line}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="pt-2 border-t border-surface-container">
                        <button
                          type="button"
                          onClick={() => handleForceProcess(rec.id)}
                          disabled={isProcessing}
                          className="w-full bg-primary hover:bg-primary-container text-on-primary text-action-md font-semibold py-2 px-3 rounded flex items-center justify-center gap-2 transition-all disabled:opacity-50 select-none cursor-pointer font-messina h-9"
                        >
                          {isProcessing ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Cpu className="w-4 h-4" />}
                          <span>{isProcessing ? 'Processing...' : 'Process Screenshot'}</span>
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>

          {/* Pagination Controls */}
          {totalPages > 1 && (
            <div className="flex justify-center items-center gap-2 mt-8 pt-6 border-t border-surface-container-high font-messina select-none">
              <button
                onClick={() => fetchHistory(currentPage - 1)}
                disabled={currentPage === 1}
                className="h-10 px-4 rounded border border-surface-container-high bg-surface-container-lowest hover:bg-surface-container-low text-neutral-dark text-action-md font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer flex items-center justify-center"
              >
                Previous
              </button>

              {getPageRange().map((p) => (
                <button
                  key={p}
                  onClick={() => fetchHistory(p)}
                  className={`h-10 w-10 rounded border text-action-md font-medium flex items-center justify-center transition-colors cursor-pointer ${
                    currentPage === p
                      ? 'bg-primary border-primary text-on-primary font-semibold'
                      : 'border-surface-container-high bg-surface-container-lowest hover:bg-surface-container-low text-neutral-dark'
                  }`}
                >
                  {p}
                </button>
              ))}

              <button
                onClick={() => fetchHistory(currentPage + 1)}
                disabled={currentPage === totalPages}
                className="h-10 px-4 rounded border border-surface-container-high bg-surface-container-lowest hover:bg-surface-container-low text-neutral-dark text-action-md font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer flex items-center justify-center"
              >
                Next
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
