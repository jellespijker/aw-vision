import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { Save, FileText, Calendar, Clock, ZoomIn, ZoomOut, BarChart3, AlertCircle } from 'lucide-react'
import { Project, ProjectsTimelineResponse } from '../types'


interface ProjectsTabProps {
  projectsList: Project[]
  projectsJsonInput: string
  setProjectsJsonInput: (val: string) => void
  saveProjectsJson: () => void
  savingProjects: boolean
}

const RESOLUTION_SECONDS_MAP: Record<string, number> = {
  '1m': 60,
  '5m': 300,
  '10m': 600,
  '15m': 900,
  '30m': 1800,
  '1h': 3600,
  '1d': 86400,
  '1w': 604800,
  '1M': 2592000,
}

const RESOLUTIONS = [
  { key: '1m', label: '1 min' },
  { key: '5m', label: '5 min' },
  { key: '10m', label: '10 min' },
  { key: '15m', label: '15 min' },
  { key: '30m', label: '30 min' },
  { key: '1h', label: '1 hour' },
  { key: '1d', label: '1 day' },
  { key: '1w', label: '1 week' },
  { key: '1M', label: '1 month' },
]

const RANGES = [
  { key: 'today', label: 'Today' },
  { key: 'yesterday', label: 'Yesterday' },
  { key: 'last24h', label: 'Last 24 Hours' },
  { key: 'last7d', label: 'Last 7 Days' },
  { key: 'last30d', label: 'Last 30 Days' },
]

export const ProjectsTab: React.FC<ProjectsTabProps> = ({
  projectsList,
  projectsJsonInput,
  setProjectsJsonInput,
  saveProjectsJson,
  savingProjects
}) => {
  // Filters & Aggregation States
  const [selectedRange, setSelectedRange] = useState<string>('today')
  const [selectedResolution, setSelectedResolution] = useState<string>('30m')
  const [timelineData, setTimelineData] = useState<ProjectsTimelineResponse | null>(null)
  const [loadingTimeline, setLoadingTimeline] = useState<boolean>(false)
  const [errorTimeline, setErrorTimeline] = useState<string | null>(null)

  // Auto-adjust resolution when range changes to keep grid density readable
  useEffect(() => {
    if (selectedRange === 'today' || selectedRange === 'yesterday' || selectedRange === 'last24h') {
      setSelectedResolution('30m')
    } else if (selectedRange === 'last7d') {
      setSelectedResolution('1h')
    } else if (selectedRange === 'last30d') {
      setSelectedResolution('1d')
    }
  }, [selectedRange])

  // Fetch timeline data whenever filters change
  useEffect(() => {
    fetchTimeline()
  }, [selectedRange, selectedResolution])

  const getTimestampsForRange = (range: string) => {
    const now = Date.now() / 1000
    let start = now - 24 * 60 * 60

    if (range === 'today') {
      const d = new Date()
      d.setHours(0, 0, 0, 0)
      start = d.getTime() / 1000
    } else if (range === 'yesterday') {
      const d = new Date()
      d.setDate(d.getDate() - 1)
      d.setHours(0, 0, 0, 0)
      start = d.getTime() / 1000
      const dEnd = new Date()
      dEnd.setHours(0, 0, 0, 0)
      return { start, end: dEnd.getTime() / 1000 }
    } else if (range === 'last24h') {
      start = now - 24 * 60 * 60
    } else if (range === 'last7d') {
      start = now - 7 * 24 * 60 * 60
    } else if (range === 'last30d') {
      start = now - 30 * 24 * 60 * 60
    }

    return { start, end: now }
  }

  const fetchTimeline = async () => {
    setLoadingTimeline(true)
    setErrorTimeline(null)
    try {
      const { start, end } = getTimestampsForRange(selectedRange)
      const resp = await axios.get<ProjectsTimelineResponse>(
        `/api/projects/timeline?start_time=${start}&end_time=${end}&resolution=${selectedResolution}`
      )
      setTimelineData(resp.data)
    } catch (err: any) {
      console.error('Failed to load project binned timeline', err)
      setErrorTimeline(err.response?.data?.detail || err.message || 'Network error loading timeline')
    } finally {
      setLoadingTimeline(false)
    }
  }

  const handleZoom = (direction: 'in' | 'out') => {
    const currentIndex = RESOLUTIONS.findIndex((r) => r.key === selectedResolution)
    if (direction === 'in' && currentIndex > 0) {
      setSelectedResolution(RESOLUTIONS[currentIndex - 1].key)
    } else if (direction === 'out' && currentIndex < RESOLUTIONS.length - 1) {
      setSelectedResolution(RESOLUTIONS[currentIndex + 1].key)
    }
  }

  const getProgressPercent = (hours: number) => {
    if (!hours) return 0
    const maxTracked = Math.max(...projectsList.map((p) => p.tracked_hours || 0), 10)
    return Math.min(100, (hours / maxTracked) * 100)
  }

  const formatDuration = (seconds: number) => {
    if (seconds === 0) return 'No activity'
    const mins = Math.floor(seconds / 60)
    if (mins < 60) {
      return `${mins}m`
    }
    const hrs = Math.floor(mins / 60)
    const remMins = mins % 60
    return remMins > 0 ? `${hrs}h ${remMins}m` : `${hrs}h`
  }

  const formatInterval = (start: number, end: number, resolution: string) => {
    const sDate = new Date(start * 1000)
    const eDate = new Date(end * 1000)

    if (['1m', '5m', '10m', '15m', '30m', '1h'].includes(resolution)) {
      return `${sDate.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} ${sDate.toLocaleTimeString(
        undefined,
        { hour: '2-digit', minute: '2-digit' }
      )} - ${eDate.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}`
    } else {
      return `${sDate.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} - ${eDate.toLocaleDateString(
        undefined,
        { month: 'short', day: 'numeric' }
      )}`
    }
  }

  return (
    <div className="space-y-6 font-sans">
      {/* SECTION 1: GANTT HEATMAP TIMELINE */}
      <div className="bg-surface-container-lowest border border-surface-container-high p-6 rounded-lg space-y-5">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <div className="space-y-1">
            <h3 className="font-semibold text-headline-sm text-neutral-dark flex items-center gap-2">
              <BarChart3 className="w-5 h-5 text-primary animate-pulse" /> Project Gantt Timeline density heatmap
            </h3>
            <p className="text-text-secondary text-body-sm">
              Displays non-AFK work sessions binned dynamically at selected grid resolution. Darker blocks indicate higher active intensity.
            </p>
          </div>

          {/* Interactive Controls */}
          <div className="flex flex-wrap items-center gap-3 shrink-0">
            {/* Time Range Selector */}
            <div className="flex bg-surface-container rounded-md p-1 border border-outline-variant/20">
              {RANGES.map((r) => (
                <button
                  key={r.key}
                  onClick={() => setSelectedRange(r.key)}
                  className={`px-3 py-1.5 rounded text-technical-sm font-medium transition-all cursor-pointer select-none ${
                    selectedRange === r.key
                      ? 'bg-surface-container-lowest shadow-sm text-primary'
                      : 'text-text-secondary hover:text-neutral-dark'
                  }`}
                >
                  {r.label}
                </button>
              ))}
            </div>

            {/* Resolution Selector Dropdown */}
            <div className="flex items-center gap-2 border border-outline-variant/30 rounded-md p-1 bg-surface-container">
              <Clock className="w-4 h-4 text-text-secondary ml-1.5" />
              <select
                value={selectedResolution}
                onChange={(e) => setSelectedResolution(e.target.value)}
                className="bg-transparent text-technical-sm text-neutral-dark font-medium focus:outline-none pr-2 py-1 select-none cursor-pointer"
              >
                {RESOLUTIONS.map((res) => (
                  <option key={res.key} value={res.key}>
                    {res.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Zoom controls */}
            <div className="flex bg-surface-container border border-outline-variant/30 rounded-md overflow-hidden">
              <button
                onClick={() => handleZoom('in')}
                disabled={selectedResolution === '1m'}
                title="Zoom In (Finer Resolution)"
                className="p-1.5 hover:bg-surface-container-high text-neutral-dark disabled:opacity-40 transition-colors cursor-pointer"
              >
                <ZoomIn className="w-4 h-4" />
              </button>
              <div className="w-[1px] bg-outline-variant/20 self-stretch" />
              <button
                onClick={() => handleZoom('out')}
                disabled={selectedResolution === '1M'}
                title="Zoom Out (Coarser Resolution)"
                className="p-1.5 hover:bg-surface-container-high text-neutral-dark disabled:opacity-40 transition-colors cursor-pointer"
              >
                <ZoomOut className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>

        {/* Loading Spinner State */}
        {loadingTimeline && (
          <div className="h-64 flex flex-col items-center justify-center space-y-3 bg-surface-container-low/20 rounded border border-dashed border-outline-variant/30">
            <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin"></div>
            <span className="text-text-secondary text-body-sm font-medium animate-pulse">
              Aggregating and rendering database sessions...
            </span>
          </div>
        )}

        {/* Error State */}
        {errorTimeline && !loadingTimeline && (
          <div className="h-64 flex flex-col items-center justify-center p-6 text-center space-y-2 bg-danger-primary/5 rounded border border-danger-primary/20">
            <AlertCircle className="w-8 h-8 text-danger-primary" />
            <strong className="text-neutral-dark text-headline-sm">Failed to load binned timeline</strong>
            <p className="text-text-secondary text-body-sm max-w-md">{errorTimeline}</p>
          </div>
        )}

        {/* Gantt Timeline Heatmap Grid */}
        {!loadingTimeline && !errorTimeline && timelineData && (
          <div className="overflow-x-auto border border-surface-container-high rounded-lg scrollbar-thin bg-surface-container-lowest shadow-sm max-w-full">
            <div className="min-w-max">
              {/* Columns Header Row */}
              <div className="flex border-b border-surface-container-high py-3 font-medium text-technical-sm text-text-secondary bg-surface-container-low/30">
                <div className="sticky left-0 bg-surface-container-lowest z-10 w-48 shrink-0 pl-4 border-r border-surface-container-high flex items-center">
                  Project Number
                </div>
                <div className="flex gap-1 px-4">
                  {timelineData.timeline_headers.map((h, hIdx) => (
                    <div
                      key={hIdx}
                      className="w-8 shrink-0 text-center text-[10px] font-mono tracking-tighter select-none font-semibold truncate"
                      title={new Date(h.timestamp * 1000).toLocaleString()}
                    >
                      {h.label}
                    </div>
                  ))}
                </div>
              </div>

              {/* Grid Content Rows */}
              {timelineData.projects.length === 0 ? (
                <div className="p-12 text-center text-text-secondary text-body-sm">
                  No active session metrics found for the selected range.
                </div>
              ) : (
                <div className="divide-y divide-surface-container-high/40">
                  {timelineData.projects.map((proj) => (
                    <div
                      key={proj.project_number}
                      className="flex py-3.5 hover:bg-surface-container-low/10 items-center transition-colors"
                    >
                      {/* Left: Sticky Project Meta Info */}
                      <div className="sticky left-0 bg-surface-container-lowest z-10 w-48 shrink-0 pl-4 border-r border-surface-container-high flex flex-col justify-center select-none shadow-[2px_0_5px_rgba(0,0,0,0.01)]">
                        <div className="flex items-center gap-2">
                          <span
                            className="w-2.5 h-2.5 rounded-full shrink-0 shadow-sm"
                            style={{ backgroundColor: proj.color }}
                          />
                          <strong
                            className="text-neutral-dark text-technical-sm font-semibold truncate w-24"
                            title={`${proj.project_number} - ${proj.description}`}
                          >
                            {proj.project_number}
                          </strong>
                          <span className="text-[10px] text-primary font-mono ml-auto pr-3 font-semibold">
                            {(proj.total_duration_seconds / 3600).toFixed(1)} h
                          </span>
                        </div>
                      </div>

                      {/* Right: Heatmap blocks */}
                      <div className="flex gap-1 px-4">
                        {proj.bins.map((bin, binIdx) => {
                          const resSec = RESOLUTION_SECONDS_MAP[selectedResolution] || 3600
                          const density = Math.min(1, bin.duration_seconds / resSec)

                          // Generate dynamic alpha opacity variant of custom HSL color
                          const bgStyle =
                            bin.duration_seconds > 0
                              ? {
                                  backgroundColor: proj.color
                                    .replace('hsl(', 'hsla(')
                                    .replace(')', `, ${0.15 + density * 0.85})`),
                                }
                              : {}

                          const hoverTooltip = `${proj.project_number} (${proj.description || 'Unclassified'})\nTime: ${formatInterval(
                            bin.start_time,
                            bin.end_time,
                            selectedResolution
                          )}\nDuration: ${formatDuration(bin.duration_seconds)}`

                          return (
                            <div
                              key={binIdx}
                              style={bgStyle}
                              title={hoverTooltip}
                              className={`w-8 h-8 rounded shrink-0 transition-all duration-150 cursor-pointer ${
                                bin.duration_seconds > 0
                                  ? 'hover:scale-110 hover:shadow shadow-primary/20 border border-transparent hover:z-20'
                                  : 'bg-surface-container-low/30 border border-surface-container-high/10 hover:border-primary/25 hover:bg-surface-container/50'
                              }`}
                            />
                          )
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* SECTION 2: TRACKED LISTING & JSON EDITOR (SIDE-BY-SIDE BELOW CHART) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Tracked Project Listing */}
        <div className="lg:col-span-2 bg-surface-container-lowest border border-surface-container-high p-6 rounded-lg space-y-4">
          <div>
            <h3 className="font-semibold text-headline-sm text-neutral-dark">
              Cumulative Hours by Project Guidelines
            </h3>
            <p className="text-text-secondary text-body-sm mt-1">
              All-time compiled durations automatically computed by evaluating match criteria across historical screenshot OCR texts.
            </p>
          </div>

          {projectsList.length === 0 ? (
            <p className="text-text-secondary text-body-sm">No active guidelines defined.</p>
          ) : (
            <div className="space-y-4 pt-2">
              {projectsList.map((proj) => (
                <div
                  key={proj.project_number}
                  className="p-4 bg-surface-container-low rounded border border-surface-container-high hover:bg-surface-container transition-colors space-y-3"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <span className="bg-primary text-on-primary text-technical-sm font-semibold px-3 py-1 rounded">
                        {proj.project_number}
                      </span>
                      <strong className="text-neutral-dark text-headline-sm">{proj.description}</strong>
                    </div>
                    <span className="text-display-progress text-primary font-noto font-bold tracking-tight">
                      {proj.tracked_hours || 0} h
                    </span>
                  </div>

                  <p className="text-text-secondary text-body-sm leading-relaxed">
                    {proj.work_entailment}
                  </p>

                  <div className="space-y-1">
                    <div className="w-full h-2 bg-surface-container rounded-full overflow-hidden">
                      <div
                        className="h-full bg-primary rounded-full transition-all duration-500"
                        style={{ width: `${getProgressPercent(proj.tracked_hours)}%` }}
                      ></div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Configuration JSON Editor */}
        <div className="bg-surface-container-lowest border border-surface-container-high p-5 rounded-lg h-fit space-y-4">
          <div>
            <h3 className="font-semibold text-headline-sm text-neutral-dark flex items-center gap-2">
              <FileText className="w-4 h-4 text-primary" /> Configure Guidelines
            </h3>
            <p className="text-text-secondary text-body-sm mt-1 leading-relaxed">
              Define project guidelines as JSON. This criteria dictates how the LLM vision system
              automatically categorizes and segments newly indexed screenshots.
            </p>
          </div>

          <textarea
            value={projectsJsonInput}
            onChange={(e) => setProjectsJsonInput(e.target.value)}
            rows={12}
            className="w-full p-3 font-mono text-technical-sm text-neutral-dark bg-surface-container-low border border-surface-container-high rounded focus:outline-none focus:border-primary"
          ></textarea>

          <button
            onClick={saveProjectsJson}
            disabled={savingProjects}
            className="w-full bg-primary hover:bg-primary-container text-on-primary font-messina text-action-lg font-medium h-10 px-4 rounded flex items-center justify-center gap-2 transition-colors disabled:opacity-50 select-none cursor-pointer"
          >
            <Save className="w-4 h-4" />
            {savingProjects ? 'Saving...' : 'Save Configurations'}
          </button>
        </div>
      </div>
    </div>
  )
}
