import React from 'react'
import axios from 'axios'
import {
  Database,
  Cpu,
  Activity,
  Info,
  Shield,
  RefreshCw,
  Server,
  CheckCircle,
  Clock,
  Loader2,
  AlertTriangle,
  BarChart3,
  Type,
  Eye,
  Hash,
  Zap
} from 'lucide-react'
import type { DaemonStatus, ProcessingStats } from '../types'
import { ReprocessToggles } from './ReprocessToggles'

interface PipelineTabProps {
  status: DaemonStatus | null
  bulkProcessing: boolean
  handleProcessAll: () => void
  reprocessRange: string
  setReprocessRange: (val: string) => void
  reprocessOcr: boolean
  setReprocessOcr: (val: boolean) => void
  reprocessLowConfOnly: boolean
  setReprocessLowConfOnly: (val: boolean) => void
  reprocessing: boolean
  handleBulkReprocessSidebar: () => void
}

export const PipelineTab: React.FC<PipelineTabProps> = ({
  status,
  bulkProcessing,
  handleProcessAll,
  reprocessRange,
  setReprocessRange,
  reprocessOcr,
  setReprocessOcr,
  reprocessLowConfOnly,
  setReprocessLowConfOnly,
  reprocessing,
  handleBulkReprocessSidebar
}) => {
  const [stats, setStats] = React.useState<ProcessingStats | null>(null)
  const [loadingStats, setLoadingStats] = React.useState<boolean>(false)

  const fetchStats = async () => {
    try {
      setLoadingStats(true)
      const resp = await axios.get('/api/stats/processing')
      setStats(resp.data)
    } catch (e) {
      console.error('Error fetching processing stats', e)
    } finally {
      setLoadingStats(false)
    }
  }

  React.useEffect(() => {
    fetchStats()
  }, [])

  return (
    <div className="font-sans space-y-6">
      {/* Untitled UI Page Header */}
      <div className="border-b border-surface-container-high pb-5">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="text-[11px] font-semibold text-primary uppercase tracking-wider bg-accent-surface border border-primary/10 px-2.5 py-0.5 rounded font-mono select-none">
                System Ingestion Core
              </span>
              <span className="w-1.5 h-1.5 rounded-full bg-success-green animate-pulse" />
              <span className="text-[11px] font-medium text-text-secondary">Active Daemon Loop</span>
            </div>
            <h2 className="text-2xl md:text-3xl font-bold text-neutral-dark tracking-tight">
              Pipeline &amp; Processing
            </h2>
            <p className="text-text-secondary text-body-md mt-1.5 max-w-2xl leading-relaxed">
              Monitor desktop screenshot capture ingestion queues, analyze host CPU/RAM allocations, and trigger bulk database reprocessing sweeps.
            </p>
          </div>
        </div>
      </div>

      {!status ? (
        <div className="h-64 rounded-lg border border-dashed border-surface-container-high bg-surface-container-lowest flex flex-col items-center justify-center p-6 space-y-3">
          <Clock className="w-8 h-8 text-text-secondary animate-pulse" />
          <h2 className="font-semibold text-headline-sm text-neutral-dark">Loading Pipeline Diagnostics</h2>
          <p className="text-text-secondary text-body-sm text-center max-w-sm">
            Fetching active daemon status metrics from the local aw-vision backend...
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left Column: Diagnostics (7 columns) */}
          <div className="lg:col-span-7 space-y-6">
            {/* Status Queue Card */}
            <div className="bg-surface-container-lowest border border-surface-container-high p-6 rounded-lg space-y-5">
              <div className="flex items-center justify-between border-b border-surface-container-high pb-4">
                <h2 className="font-bold text-headline-sm text-neutral-dark flex items-center gap-2">
                  <Database className="w-5 h-5 text-primary" /> Active Queue Ingestion
                </h2>
                <span className="text-[11px] font-semibold text-text-secondary uppercase tracking-wider font-mono">
                  LanceDB Local DB
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Pending queue */}
                <div className="p-4 bg-surface-container-low rounded border border-surface-container-high space-y-1">
                  <span className="text-text-secondary font-medium text-body-sm">Screenshots Pending</span>
                  <div className="flex items-baseline gap-2 pt-1">
                    <span className="text-2xl font-bold text-neutral-dark font-mono">
                      {status.pending_queue_size}
                    </span>
                    <span className="text-technical-sm font-semibold text-text-secondary">files</span>
                  </div>
                </div>

                {/* Database size */}
                <div className="p-4 bg-surface-container-low rounded border border-surface-container-high space-y-1">
                  <span className="text-text-secondary font-medium text-body-sm">Screenshots Indexed</span>
                  <div className="flex items-baseline gap-2 pt-1">
                    <span className="text-2xl font-bold text-neutral-dark font-mono">
                      {status.processed_database_size}
                    </span>
                    <span className="text-technical-sm font-semibold text-text-secondary">records</span>
                  </div>
                </div>
              </div>

              {/* Progress visual */}
              <div className="space-y-2">
                <div className="flex justify-between items-center text-technical-sm font-mono text-text-secondary">
                  <span>Processing Progress</span>
                  <span>
                    {Math.round(
                      (status.processed_database_size /
                        (status.processed_database_size + status.pending_queue_size || 1)) *
                        100
                    )}
                    %
                  </span>
                </div>
                <div className="w-full h-2.5 bg-surface-container rounded-full overflow-hidden">
                  <div
                    className="h-full bg-primary rounded-full transition-all duration-500"
                    style={{
                      width: `${
                        (status.processed_database_size /
                          (status.processed_database_size + status.pending_queue_size || 1)) *
                        100
                      }%`
                    }}
                  ></div>
                </div>
              </div>

              {/* Active Sweep Ingestion Progress Panel */}
              {status.is_processing && (
                <div className="bg-primary/5 border border-primary/10 rounded-lg p-4 space-y-3 relative overflow-hidden backdrop-blur-md">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="relative flex h-2 w-2">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75"></span>
                        <span className="relative inline-flex rounded-full h-2 w-2 bg-primary"></span>
                      </span>
                      <span className="text-body-sm font-bold text-neutral-dark font-sans">
                        Active Ingestion Sweep
                      </span>
                    </div>
                    <span className="text-technical-sm font-mono font-semibold text-primary">
                      {Math.round(
                        (((status.current_batch_processed || 0) / (status.current_batch_total || 1)) * 100)
                      )}
                      %
                    </span>
                  </div>

                  <div className="w-full h-2 bg-surface-container rounded-full overflow-hidden">
                    <div
                      className="h-full bg-primary rounded-full transition-all duration-300"
                      style={{
                        width: `${
                          (((status.current_batch_processed || 0) / (status.current_batch_total || 1)) * 100)
                        }%`
                      }}
                    ></div>
                  </div>

                  <div className="flex flex-col gap-1.5 text-body-sm text-text-secondary">
                    <div className="flex justify-between items-start gap-4">
                      <span className="font-medium text-neutral-dark flex items-center gap-1.5 font-sans">
                        <Loader2 className="w-3.5 h-3.5 text-primary animate-spin shrink-0" />
                        {status.current_stage || "Processing batch item..."}
                      </span>
                      <span className="text-technical-sm font-mono shrink-0">
                        {status.current_batch_processed} / {status.current_batch_total} files
                      </span>
                    </div>
                    {status.current_rec_id && (
                      <div className="flex items-center gap-1.5 text-technical-sm font-mono mt-0.5">
                        <span className="text-text-secondary">Active ID:</span>
                        <span className="bg-surface-container-low text-neutral-dark px-1.5 py-0.5 rounded border border-surface-container-high">
                          {status.current_rec_id}
                        </span>
                      </div>
                    )}
                  </div>

                  {status.last_error && (
                    <div className="bg-danger-surface border border-danger-primary/30 text-danger-primary dark:bg-danger-primary/10 dark:border-danger-primary/30 p-2.5 rounded text-technical-sm flex items-start gap-2 mt-1 font-sans">
                      <AlertTriangle className="w-4 h-4 text-danger-primary shrink-0 mt-0.5" />
                      <div className="flex-1">
                        <strong className="font-semibold">Last Ingestion Warning:</strong>{" "}
                        <span className="font-mono text-technical-sm break-all">{status.last_error}</span>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Force process */}
              {status.pending_queue_size > 0 && (
                <div className="pt-2 border-t border-surface-container-high flex flex-col md:flex-row md:items-center gap-4 justify-between">
                  <p className="text-text-secondary text-body-sm leading-relaxed max-w-md font-sans">
                    Force immediate local pipeline sweep to execute OCR extraction and vision analysis on pending screenshots.
                  </p>
                  <button
                    type="button"
                    onClick={handleProcessAll}
                    disabled={bulkProcessing || status.is_processing}
                    className="bg-accent-surface hover:bg-surface-container text-primary text-action-md font-bold py-2.5 px-4 rounded border border-primary/20 transition-colors select-none flex items-center justify-center gap-2 cursor-pointer h-10 shrink-0 disabled:opacity-50"
                  >
                    {bulkProcessing || status.is_processing ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        Processing Ingestion Queue...
                      </>
                    ) : (
                      <>
                        <Cpu className="w-4 h-4" />
                        Force Sweep Queue
                      </>
                    )}
                  </button>
                </div>
              )}
            </div>

            {/* Hardware Resource Usage Card */}
            {status.system_load && (
              <div className="bg-surface-container-lowest border border-surface-container-high p-6 rounded-lg space-y-4">
                <h2 className="font-bold text-headline-sm text-neutral-dark flex items-center gap-2 border-b border-surface-container-high pb-4">
                  <Server className="w-5 h-5 text-primary" /> Hardware Metrics &amp; Resources
                </h2>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* CPU percent */}
                  <div className="p-4 bg-surface-container-low rounded border border-surface-container-high space-y-3">
                    <div className="flex justify-between items-center">
                      <span className="text-text-secondary font-medium text-body-sm flex items-center gap-1.5">
                        <Cpu className="w-4 h-4 text-primary" /> CPU Utilization
                      </span>
                      <span className="text-headline-sm font-bold text-neutral-dark font-mono">
                        {status.system_load.cpu_percent}%
                      </span>
                    </div>
                    <div className="w-full h-2 bg-surface-container rounded-full overflow-hidden">
                      <div
                        className="h-full bg-primary rounded-full transition-all"
                        style={{ width: `${status.system_load.cpu_percent}%` }}
                      ></div>
                    </div>
                  </div>

                  {/* RAM percent */}
                  <div className="p-4 bg-surface-container-low rounded border border-surface-container-high space-y-3">
                    <div className="flex justify-between items-center">
                      <span className="text-text-secondary font-medium text-body-sm flex items-center gap-1.5">
                        <Activity className="w-4 h-4 text-primary" /> RAM Utilization
                      </span>
                      <span className="text-headline-sm font-bold text-neutral-dark font-mono">
                        {status.system_load.memory_percent}%
                      </span>
                    </div>
                    <div className="w-full h-2 bg-surface-container rounded-full overflow-hidden">
                      <div
                        className="h-full bg-primary rounded-full transition-all"
                        style={{ width: `${status.system_load.memory_percent}%` }}
                      ></div>
                    </div>
                  </div>
                </div>

                <div className="p-4 bg-surface-container-low rounded border border-surface-container-high text-body-sm text-text-secondary flex items-start gap-2.5 leading-relaxed font-sans">
                  <Info className="w-4.5 h-4.5 text-primary shrink-0 mt-0.5" />
                  <div>
                    <strong className="text-neutral-dark">CPU-Aware Throttling:</strong> To ensure zero computer performance impact while gaming or compiling code, the background pipeline loop only schedules heavy ML model executions when host CPU utilization falls below critical thresholds.
                  </div>
                </div>
              </div>
            )}

            {/* Processing Performance Statistics Card */}
            <div className="bg-surface-container-lowest border border-surface-container-high p-6 rounded-lg space-y-5">
              <div className="flex items-center justify-between border-b border-surface-container-high pb-4">
                <h2 className="font-bold text-headline-sm text-neutral-dark flex items-center gap-2">
                  <BarChart3 className="w-5 h-5 text-primary" /> Processing Performance
                </h2>
                <button
                  type="button"
                  onClick={fetchStats}
                  disabled={loadingStats}
                  className="p-1.5 text-text-secondary hover:text-neutral-dark hover:bg-surface-container-low rounded-md transition-all border border-surface-container-high cursor-pointer flex items-center justify-center disabled:opacity-50"
                  title="Refresh statistics"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${loadingStats ? 'animate-spin' : ''}`} />
                </button>
              </div>

              {!stats ? (
                <div className="flex items-center justify-center py-8 text-body-sm text-text-secondary">
                  <Loader2 className="w-4 h-4 animate-spin mr-2" />
                  Loading performance statistics...
                </div>
              ) : (
                <div className="space-y-6">
                  {/* High-Level Hero Banner */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {/* Average pipeline time */}
                    <div className="p-4 bg-surface-container-low rounded border border-surface-container-high space-y-1 relative overflow-hidden">
                      <div className="absolute top-0 right-0 p-3 opacity-10">
                        <Clock className="w-12 h-12 text-primary" />
                      </div>
                      <span className="text-text-secondary font-medium text-body-sm">Avg Ingestion Time</span>
                      <div className="flex items-baseline gap-1.5 pt-1">
                        <span className="text-3xl font-bold text-neutral-dark font-mono">
                          {stats.total?.mean ?? '0.00'}
                        </span>
                        <span className="text-technical-sm font-semibold text-text-secondary">seconds</span>
                      </div>
                      <p className="text-[11px] text-text-secondary font-sans leading-none">
                        Sum of all local model execution times
                      </p>
                    </div>

                    {/* Dataset execution count */}
                    <div className="p-4 bg-surface-container-low rounded border border-surface-container-high space-y-1 relative overflow-hidden">
                      <div className="absolute top-0 right-0 p-3 opacity-10">
                        <Activity className="w-12 h-12 text-primary" />
                      </div>
                      <span className="text-text-secondary font-medium text-body-sm">Telemetry Sample Size</span>
                      <div className="flex items-baseline gap-1.5 pt-1">
                        <span className="text-3xl font-bold text-neutral-dark font-mono">
                          {stats.total?.count ?? 0}
                        </span>
                        <span className="text-technical-sm font-semibold text-text-secondary">runs</span>
                      </div>
                      <p className="text-[11px] text-text-secondary font-sans leading-none">
                        Active executions (skips excluded)
                      </p>
                    </div>
                  </div>

                  {/* Visual Phase Metrics List */}
                  <div className="space-y-5">
                    <h3 className="text-technical-sm font-semibold text-text-secondary uppercase tracking-wider font-mono">
                      Phase-by-Phase Performance
                    </h3>

                    {[
                      {
                        name: 'OCR Extraction',
                        key: 'ocr' as const,
                        icon: Type,
                        desc: 'glm-ocr:q8_0 text sweep',
                        colorClass: 'bg-indigo-600',
                        barBg: 'bg-indigo-100 dark:bg-indigo-950/40',
                        textClass: 'text-indigo-600 dark:text-indigo-400',
                        gradient: 'from-indigo-500 to-indigo-600',
                      },
                      {
                        name: 'Vision Analysis',
                        key: 'vision' as const,
                        icon: Eye,
                        desc: 'gemma4 vision analysis',
                        colorClass: 'bg-violet-600',
                        barBg: 'bg-violet-100 dark:bg-violet-950/40',
                        textClass: 'text-violet-600 dark:text-violet-400',
                        gradient: 'from-violet-500 to-violet-600',
                      },
                      {
                        name: 'Embedding Generation',
                        key: 'embedding' as const,
                        icon: Hash,
                        desc: 'embeddinggemma coordinate',
                        colorClass: 'bg-emerald-600',
                        barBg: 'bg-emerald-100 dark:bg-emerald-950/40',
                        textClass: 'text-emerald-600 dark:text-emerald-400',
                        gradient: 'from-emerald-500 to-emerald-600',
                      },
                      {
                        name: 'Total Pipeline',
                        key: 'total' as const,
                        icon: Zap,
                        desc: 'Total processing iteration',
                        colorClass: 'bg-primary',
                        barBg: 'bg-surface-container',
                        textClass: 'text-primary dark:text-primary-container',
                        gradient: 'from-primary/80 to-primary',
                      },
                    ].map((phase) => {
                      const pStats = stats[phase.key] || { mean: 0, min: 0, max: 0, count: 0 };
                      
                      // Calculate percentage for progress visualization relative to total pipeline time
                      const percentage = stats.total?.mean 
                        ? Math.min(Math.max((pStats.mean / stats.total.mean) * 100, 3), 100)
                        : 0;

                      const IconComponent = phase.icon;

                      return (
                        <div key={phase.key} className="space-y-2 group">
                          {/* Header: Label, Desc, Mean */}
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <div className="p-1.5 rounded bg-surface-container border border-surface-container-high text-neutral-dark group-hover:scale-105 transition-transform">
                                <IconComponent className={`w-3.5 h-3.5 ${phase.textClass}`} />
                              </div>
                              <div>
                                <h4 className="font-semibold text-body-sm text-neutral-dark leading-none">
                                  {phase.name}
                                </h4>
                                <span className="text-[10px] text-text-secondary font-mono leading-none">
                                  {phase.desc}
                                </span>
                              </div>
                            </div>

                            <div className="text-right">
                              <span className="text-body-md font-bold text-neutral-dark font-mono">
                                {pStats.mean}s
                              </span>
                              <p className="text-[10px] text-text-secondary leading-none">
                                Average
                              </p>
                            </div>
                          </div>

                          {/* Progress Bar & Custom Scale Indicators */}
                          <div className="space-y-1.5">
                            <div className={`w-full h-3 ${phase.barBg} rounded-full overflow-hidden relative border border-surface-container-high`}>
                              <div
                                  className={`h-full bg-gradient-to-r ${phase.gradient} rounded-full transition-all duration-500`}
                                  style={{ width: `${percentage}%` }}
                              />
                            </div>

                            {/* Sub-row: Min, Max, Count */}
                            <div className="flex justify-between items-center text-[10px] font-mono text-text-secondary select-none">
                              <div className="flex gap-4">
                                <span className="flex items-center gap-1 hover:text-neutral-dark transition-colors">
                                  <span className="w-1.5 h-1.5 rounded-full bg-success-green opacity-80" />
                                  Min: <strong className="font-semibold text-neutral-dark">{pStats.min}s</strong>
                                </span>
                                <span className="flex items-center gap-1 hover:text-neutral-dark transition-colors">
                                  <span className="w-1.5 h-1.5 rounded-full bg-danger-primary opacity-80" />
                                  Max: <strong className="font-semibold text-neutral-dark">{pStats.max}s</strong>
                                </span>
                              </div>
                              <span className="bg-surface-container-low px-1.5 py-0.5 rounded border border-surface-container-high">
                                {pStats.count} samples
                              </span>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Right Column: Reprocessing & Privacy (5 columns) */}
          <div className="lg:col-span-5 space-y-6">
            {/* Database Reprocessing form */}
            <div className="bg-surface-container-lowest border border-surface-container-high p-6 rounded-lg space-y-4">
              <h2 className="font-bold text-headline-sm text-neutral-dark flex items-center gap-2 border-b border-surface-container-high pb-4">
                <RefreshCw className="w-5 h-5 text-primary" /> Database Reprocessing
              </h2>

              <p className="text-text-secondary text-body-sm leading-relaxed font-sans">
                Trigger mass sweeps across past desktop database records to re-analyze content, classify projects, and regenerate summaries.
              </p>

              <div className="space-y-4 pt-2">
                <div className="space-y-1.5">
                  <label
                    htmlFor="reprocessRangeSelect"
                    className="text-body-sm font-semibold text-text-secondary font-sans"
                  >
                    Scope of Reprocessing
                  </label>
                  <select
                    id="reprocessRangeSelect"
                    name="reprocessRangeSelect"
                    value={reprocessRange}
                    onChange={(e) => setReprocessRange(e.target.value)}
                    className="w-full bg-surface-container-low border border-surface-container-high h-10 px-3 rounded text-body-md text-neutral-dark outline-none cursor-pointer hover:border-primary transition-colors font-sans"
                  >
                    <option value="last10">Latest 10 Screenshots</option>
                    <option value="last50">Latest 50 Screenshots</option>
                    <option value="today">Today's Sessions</option>
                    <option value="last24h">Past 24 Hours</option>
                    <option value="all">Entire Database (OCR cached)</option>
                  </select>
                </div>

                <ReprocessToggles
                  reprocessOcr={reprocessOcr}
                  setReprocessOcr={setReprocessOcr}
                  reprocessLowConfOnly={reprocessLowConfOnly}
                  setReprocessLowConfOnly={setReprocessLowConfOnly}
                />

                <button
                  type="button"
                  onClick={handleBulkReprocessSidebar}
                  disabled={reprocessing || bulkProcessing || status.is_processing}
                  className="w-full bg-inverse-surface hover:opacity-90 text-inverse-on-surface text-action-md font-semibold h-11 rounded border border-inverse-surface transition-all flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50"
                >
                  {reprocessing || bulkProcessing || status.is_processing ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      {reprocessing ? 'Queueing Reprocess...' : 'Running Sweep...'}
                    </>
                  ) : (
                    <>
                      <RefreshCw className="w-4 h-4" />
                      Trigger Sweep Now
                    </>
                  )}
                </button>

                <div className="p-3 bg-surface-container-low rounded border border-surface-container-high text-technical-sm text-text-secondary leading-normal font-mono">
                  💡 <strong>OCR Cache Tip:</strong> By default, reprocessing keeps extracted text and only sweeps tags, project classifications, and visual high-level summaries. This takes only seconds!
                </div>
              </div>
            </div>

            {/* Privacy Card */}
            <div className="p-6 rounded-lg border border-surface-container-high bg-surface-container-lowest text-neutral-dark space-y-4">
              <h2 className="font-bold text-headline-sm text-neutral-dark flex items-center gap-2 border-b border-surface-container-high pb-4">
                <Shield className="w-5 h-5 text-primary" /> On-Device Privacy Seal
              </h2>
              <p className="text-text-secondary text-body-sm leading-relaxed font-sans">
                ActivityWatch Vision operates on a strict **100% on-device guarantee**. No images, raw texts, or analytics coordinates are transmitted off this device.
              </p>
              <div className="grid grid-cols-1 gap-2 pt-1 text-technical-sm font-medium text-neutral-dark">
                <div className="flex items-center gap-2">
                  <CheckCircle className="w-4 h-4 text-success-green" />
                  <span>Local OCR via GLM-OCR</span>
                </div>
                <div className="flex items-center gap-2">
                  <CheckCircle className="w-4 h-4 text-success-green" />
                  <span>Local Embedding Coordinates</span>
                </div>
                <div className="flex items-center gap-2">
                  <CheckCircle className="w-4 h-4 text-success-green" />
                  <span>14-day Screenshot Lifecycles</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
