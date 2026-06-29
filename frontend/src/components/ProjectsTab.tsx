import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { 
  Save, FileText, Calendar, Clock, ZoomIn, ZoomOut, BarChart3, AlertCircle, 
  Trash2, Archive, Check, Edit3, Wand2, Sparkles, Plus, X, Search, CheckCircle2, RefreshCw 
} from 'lucide-react'
import { Project, ProjectsTimelineResponse } from '../types'

interface ProjectsTabProps {
  projectsList: Project[]
  projectsJsonInput: string
  setProjectsJsonInput: (val: string) => void
  saveProjectsJson: () => void
  savingProjects: boolean
  onSaveProject: (project: Project) => Promise<void>
  onDeleteProject: (projectNumber: string) => Promise<void>
  onToggleProjectActive: (projectNumber: string) => Promise<void>
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
  onSaveProject,
  onDeleteProject,
  onToggleProjectActive,
  savingProjects
}) => {
  // ----------------------------------------------------
  // SECTION 1: HEATMAP TIMELINE STATE & EFFECT
  // ----------------------------------------------------
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

  // ----------------------------------------------------
  // SECTION 2: INTERACTIVE PROJECTS DASHBOARD STATE
  // ----------------------------------------------------
  const [searchQuery, setSearchQuery] = useState<string>('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'archived'>('all')

  // Inline Editing
  const [editingProjectNumber, setEditingProjectNumber] = useState<string | null>(null)
  const [editDescription, setEditDescription] = useState<string>('')
  const [editWorkEntailment, setEditWorkEntailment] = useState<string>('')

  // Double-check Confirm Deletes
  const [confirmDeleteProjectNumber, setConfirmDeleteProjectNumber] = useState<string | null>(null)

  // Manual Add Form
  const [newProjNumber, setNewProjectNumber] = useState<string>('')
  const [newDescription, setNewDescription] = useState<string>('')
  const [newWorkEntailment, setNewWorkEntailment] = useState<string>('')
  const [formError, setFormError] = useState<string | null>(null)

  // AI Suggestions
  const [suggestions, setSuggestions] = useState<Project[]>([])
  const [loadingSuggestions, setLoadingSuggestions] = useState<boolean>(false)
  const [suggestError, setSuggestError] = useState<string | null>(null)

  // Handle Manual Create Submits
  const handleManualAdd = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError(null)

    const trimmedNumber = newProjNumber.trim()
    const trimmedDesc = newDescription.trim()
    const trimmedEntail = newWorkEntailment.trim()

    if (!trimmedNumber) {
      setFormError('Project identifier or number is required.')
      return
    }
    if (!trimmedDesc) {
      setFormError('Project description is required.')
      return
    }

    // Check if duplicate project identifier
    if (projectsList.some(p => p.project_number.toLowerCase() === trimmedNumber.toLowerCase())) {
      setFormError('A project with this identifier already exists.')
      return
    }

    try {
      await onSaveProject({
        project_number: trimmedNumber,
        description: trimmedDesc,
        work_entailment: trimmedEntail,
        tracked_hours: 0.0,
        is_active: true
      })
      // Clear manual fields
      setNewProjectNumber('')
      setNewDescription('')
      setNewWorkEntailment('')
    } catch (err) {
      setFormError('Backend database error saving project.')
    }
  }

  // Handle Inline Save
  const handleSaveEdit = async (proj: Project) => {
    if (!editDescription.trim()) return
    try {
      await onSaveProject({
        ...proj,
        description: editDescription.trim(),
        work_entailment: editWorkEntailment.trim()
      })
      setEditingProjectNumber(null)
    } catch (e) {
      console.error(e)
    }
  }

  // Trigger AI Project Suggestion
  const handleTriggerSuggestions = async () => {
    setLoadingSuggestions(true)
    setSuggestError(null)
    setSuggestions([])
    try {
      const resp = await axios.post('/api/projects/suggest')
      if (resp.data.status === 'success') {
        const generated = resp.data.suggestions || []
        setSuggestions(generated)
        if (generated.length === 0) {
          setSuggestError(resp.data.message || 'No unclassified activity clusters found in the latest 100 screenshots.')
        }
      } else {
        setSuggestError(resp.data.message || 'Suggestions service returned an error status.')
      }
    } catch (err: any) {
      console.error('Failed fetching AI suggestions', err)
      setSuggestError(err.response?.data?.detail || err.message || 'Network failure communicating with backend.')
    } finally {
      setLoadingSuggestions(false)
    }
  }

  // One-Click approve suggestion
  const handleApproveSuggestion = async (sugg: Project, idx: number) => {
    try {
      await onSaveProject(sugg)
      // Filter out the approved card seamlessly from suggestions list
      setSuggestions(prev => prev.filter((_, i) => i !== idx))
    } catch (e) {
      console.error('Failed to approve suggestion', e)
    }
  }

  // Filter projects dynamically
  const filteredProjects = projectsList.filter(proj => {
    // 1. Filter by Search Query
    const query = searchQuery.toLowerCase()
    const matchesSearch = 
      proj.project_number.toLowerCase().includes(query) ||
      proj.description.toLowerCase().includes(query) ||
      proj.work_entailment.toLowerCase().includes(query)

    if (!matchesSearch) return false

    // 2. Filter by Active/Archived Status
    if (proj.project_number === 'Unclassified') return true // always show unclassified at the end

    const isProjActive = proj.is_active !== false // default undefined to true
    if (statusFilter === 'active') return isProjActive
    if (statusFilter === 'archived') return !isProjActive

    return true
  })

  // Group unclassified project separately to ensure it is always appended cleanly at the bottom
  const standardFiltered = filteredProjects.filter(p => p.project_number !== 'Unclassified')
  const unclassifiedFiltered = filteredProjects.filter(p => p.project_number === 'Unclassified')
  const finalDisplayList = [...standardFiltered, ...unclassifiedFiltered]

  return (
    <div className="space-y-6 font-sans">
      {/* SECTION 1: GANTT HEATMAP TIMELINE */}
      <div className="bg-surface-container-lowest border border-surface-container-high p-6 rounded-xl shadow-xs space-y-5">
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
                      ? 'bg-surface-container-lowest shadow-sm text-primary font-semibold'
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
          <div className="h-64 flex flex-col items-center justify-center space-y-3 bg-surface-container-low/20 rounded border border-dashed border-outline-variant/30 animate-pulse-slow">
            <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin"></div>
            <span className="text-text-secondary text-body-sm font-medium">
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

      {/* SECTION 2: INTERACTIVE GUIDELINES & SUGGESTER (DASHBOARD REDESIGN) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Side: Project Guidelines Card List (2/3 width) */}
        <div className="lg:col-span-2 space-y-4">
          <div className="bg-surface-container-lowest border border-surface-container-high p-5 rounded-xl shadow-xs space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
              <div>
                <h4 className="font-semibold text-headline-sm text-neutral-dark">
                  Project Classification Guidelines
                </h4>
                <p className="text-text-secondary text-body-sm">
                  Active match policies utilized by the local LLM pipeline to categorise raw activity into projects.
                </p>
              </div>

              {/* Status Filters pills */}
              <div className="flex bg-surface-container rounded-md p-0.5 border border-outline-variant/20 self-start sm:self-center">
                <button
                  onClick={() => setStatusFilter('all')}
                  className={`px-3 py-1 rounded text-body-sm font-medium transition-all select-none cursor-pointer ${
                    statusFilter === 'all'
                      ? 'bg-surface-container-lowest text-neutral-dark shadow-xs'
                      : 'text-text-secondary hover:text-neutral-dark'
                  }`}
                >
                  All
                </button>
                <button
                  onClick={() => setStatusFilter('active')}
                  className={`px-3 py-1 rounded text-body-sm font-medium transition-all select-none cursor-pointer ${
                    statusFilter === 'active'
                      ? 'bg-surface-container-lowest text-neutral-dark shadow-xs'
                      : 'text-text-secondary hover:text-neutral-dark'
                  }`}
                >
                  Active
                </button>
                <button
                  onClick={() => setStatusFilter('archived')}
                  className={`px-3 py-1 rounded text-body-sm font-medium transition-all select-none cursor-pointer ${
                    statusFilter === 'archived'
                      ? 'bg-surface-container-lowest text-neutral-dark shadow-xs'
                      : 'text-text-secondary hover:text-neutral-dark'
                  }`}
                >
                  Archived
                </button>
              </div>
            </div>

            {/* Search Input */}
            <div className="relative">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-text-secondary" />
              <input
                type="text"
                placeholder="Search guidelines by number, details or keywords..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-10 pr-4 py-2 text-body-md text-neutral-dark bg-surface-container-low border border-surface-container-high rounded-lg focus:outline-none focus:border-primary transition-all placeholder:text-text-secondary/60"
              />
              {searchQuery && (
                <button 
                  onClick={() => setSearchQuery('')}
                  className="absolute right-3 top-2.5 text-text-secondary hover:text-neutral-dark cursor-pointer"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>
          </div>

          {/* Cards Grid */}
          <div className="space-y-4">
            {finalDisplayList.length === 0 ? (
              <div className="p-12 text-center bg-surface-container-lowest border border-surface-container-high rounded-xl space-y-2">
                <AlertCircle className="w-8 h-8 text-text-secondary mx-auto" />
                <strong className="text-neutral-dark text-headline-sm block">No guidelines match your filters</strong>
                <p className="text-text-secondary text-body-sm max-w-sm mx-auto">
                  Try adjusting your search keywords, status filters, or create a brand new guideline.
                </p>
              </div>
            ) : (
              finalDisplayList.map((proj) => {
                const isEditing = editingProjectNumber === proj.project_number
                const isUnclassified = proj.project_number === 'Unclassified'
                const isArchived = proj.is_active === false

                return (
                  <div
                    key={proj.project_number}
                    className={`p-5 rounded-xl border transition-all duration-250 bg-surface-container-lowest ${
                      isEditing 
                        ? 'border-primary shadow-md ring-2 ring-primary/10' 
                        : isUnclassified
                          ? 'border-outline-variant/30 border-dashed bg-surface-container-low/20'
                          : isArchived
                            ? 'border-surface-container-high opacity-70 grayscale-30 bg-surface-container-low/10'
                            : 'border-surface-container-high shadow-xs hover:shadow-md hover:border-outline-variant/40'
                    }`}
                  >
                    {isEditing ? (
                      /* Inline Editing Fields */
                      <div className="space-y-4">
                        <div className="flex items-center justify-between">
                          <span className="bg-primary text-on-primary text-technical-sm font-semibold px-2.5 py-1 rounded">
                            {proj.project_number}
                          </span>
                          <span className="text-text-secondary text-body-sm italic">
                            Modifying project guidelines...
                          </span>
                        </div>

                        <div className="space-y-3">
                          <div className="space-y-1">
                            <label className="text-technical-sm font-semibold text-neutral-dark">Description</label>
                            <input
                              type="text"
                              value={editDescription}
                              onChange={(e) => setEditDescription(e.target.value)}
                              className="w-full px-3 py-1.5 text-body-md text-neutral-dark bg-surface-container-low border border-surface-container-high rounded focus:outline-none focus:border-primary focus:bg-surface-container-lowest"
                            />
                          </div>

                          <div className="space-y-1">
                            <label className="text-technical-sm font-semibold text-neutral-dark">Work Entailment / Rules</label>
                            <textarea
                              rows={3}
                              value={editWorkEntailment}
                              onChange={(e) => setEditWorkEntailment(e.target.value)}
                              className="w-full p-3 text-body-md text-neutral-dark bg-surface-container-low border border-surface-container-high rounded focus:outline-none focus:border-primary focus:bg-surface-container-lowest font-sans leading-relaxed"
                            />
                          </div>
                        </div>

                        <div className="flex justify-end gap-2 pt-1 border-t border-surface-container-high">
                          <button
                            onClick={() => setEditingProjectNumber(null)}
                            className="px-3.5 h-8 text-action-md font-medium text-text-secondary hover:bg-surface-container rounded-md transition-colors cursor-pointer select-none"
                          >
                            Cancel
                          </button>
                          <button
                            onClick={() => handleSaveEdit(proj)}
                            disabled={savingProjects}
                            className="px-4 h-8 text-action-md font-semibold text-on-primary bg-primary hover:bg-primary-container rounded-md flex items-center gap-1.5 transition-colors cursor-pointer select-none"
                          >
                            <Check className="w-3.5 h-3.5" /> Save Changes
                          </button>
                        </div>
                      </div>
                    ) : (
                      /* Standard Guideline Rendering */
                      <div className="space-y-4">
                        <div className="flex items-start justify-between gap-4">
                          <div className="space-y-1">
                            <div className="flex items-center flex-wrap gap-2.5">
                              <span className={`text-technical-sm font-bold px-2.5 py-1 rounded select-none ${
                                isUnclassified 
                                  ? 'bg-surface-container text-text-secondary' 
                                  : isArchived 
                                    ? 'bg-surface-container text-disabled line-through' 
                                    : 'bg-primary text-on-primary'
                              }`}>
                                {proj.project_number}
                              </span>

                              {/* Interactive Tags */}
                              {isUnclassified ? (
                                <span className="bg-surface-container text-text-secondary text-[10px] uppercase font-semibold px-2 py-0.5 rounded flex items-center gap-1 border border-outline-variant/30">
                                  System Default
                                </span>
                              ) : isArchived ? (
                                <span className="bg-warning-light text-tertiary-container text-[10px] uppercase font-bold px-2 py-0.5 rounded flex items-center gap-1">
                                  Archived
                                </span>
                              ) : (
                                <span className="bg-success-green/10 text-success-green text-[10px] uppercase font-bold px-2 py-0.5 rounded flex items-center gap-1">
                                  <span className="w-1.5 h-1.5 rounded-full bg-success-green animate-pulse" /> Active
                                </span>
                              )}
                            </div>
                            <strong className="text-neutral-dark text-headline-sm block mt-1">
                              {proj.description}
                            </strong>
                          </div>

                          {/* Quick Interactive Actions */}
                          {!isUnclassified && (
                            <div className="flex items-center bg-surface-container p-1 rounded-lg border border-outline-variant/20 shrink-0">
                              {confirmDeleteProjectNumber === proj.project_number ? (
                                /* In-Card Delete Confirm State */
                                <div className="flex items-center gap-1.5 animate-pulse-slow">
                                  <span className="text-[11px] text-danger-primary font-semibold px-1.5">Confirm?</span>
                                  <button
                                    onClick={async () => {
                                      await onDeleteProject(proj.project_number)
                                      setConfirmDeleteProjectNumber(null)
                                    }}
                                    className="p-1 text-danger-primary hover:bg-danger-surface rounded transition-colors cursor-pointer"
                                    title="Yes, delete forever"
                                  >
                                    <Check className="w-3.5 h-3.5" />
                                  </button>
                                  <button
                                    onClick={() => setConfirmDeleteProjectNumber(null)}
                                    className="p-1 text-text-secondary hover:bg-surface-container-high rounded transition-colors cursor-pointer"
                                    title="Cancel"
                                  >
                                    <X className="w-3.5 h-3.5" />
                                  </button>
                                </div>
                              ) : (
                                /* Normal actions icon dock */
                                <div className="flex items-center">
                                  <button
                                    onClick={() => {
                                      setEditingProjectNumber(proj.project_number)
                                      setEditDescription(proj.description)
                                      setEditWorkEntailment(proj.work_entailment)
                                    }}
                                    className="p-1.5 text-text-secondary hover:text-neutral-dark hover:bg-surface-container-high rounded-md transition-colors cursor-pointer"
                                    title="Edit details"
                                  >
                                    <Edit3 className="w-4 h-4" />
                                  </button>
                                  <button
                                    onClick={() => onToggleProjectActive(proj.project_number)}
                                    className={`p-1.5 hover:bg-surface-container-high rounded-md transition-colors cursor-pointer ${
                                      isArchived ? 'text-text-secondary hover:text-primary' : 'text-text-secondary hover:text-tertiary-container'
                                    }`}
                                    title={isArchived ? 'Restore / Activate Project' : 'Archive / Deactivate Project'}
                                  >
                                    <Archive className="w-4 h-4" />
                                  </button>
                                  <button
                                    onClick={() => setConfirmDeleteProjectNumber(proj.project_number)}
                                    className="p-1.5 text-text-secondary hover:text-danger-primary hover:bg-danger-surface rounded-md transition-colors cursor-pointer"
                                    title="Hard delete project"
                                  >
                                    <Trash2 className="w-4 h-4" />
                                  </button>
                                </div>
                              )}
                            </div>
                          )}
                        </div>

                        {/* Rules / Match criteria content block */}
                        {proj.work_entailment ? (
                          <div className="bg-surface-container-low p-3.5 rounded-lg text-body-sm text-text-secondary leading-relaxed font-sans border border-surface-container-high/40">
                            <span className="text-[10px] uppercase font-semibold text-text-secondary/60 tracking-wider block mb-1 font-sans">
                              Work Entailment Match Criteria
                            </span>
                            {proj.work_entailment}
                          </div>
                        ) : (
                          <p className="text-text-secondary/60 text-body-sm italic">
                            No match criteria or work entailment specified. Add keywords or workflows to help the AI matching logic.
                          </p>
                        )}

                        {/* Cumulative Hours block */}
                        <div className="flex items-center justify-between gap-4 pt-1">
                          <div className="flex items-baseline gap-1.5">
                            <span className="text-display-progress text-primary font-bold pr-1 select-none">
                              {proj.tracked_hours || 0}
                            </span>
                            <span className="text-text-secondary text-technical-sm font-semibold">hours tracked</span>
                          </div>

                          {/* Relative weight visual bar */}
                          <div className="w-32 sm:w-48 space-y-1 select-none shrink-0">
                            <div className="w-full h-2 bg-surface-container rounded-full overflow-hidden border border-outline-variant/10">
                              <div
                                className={`h-full rounded-full transition-all duration-500 ${
                                  isUnclassified 
                                    ? 'bg-text-secondary/40' 
                                    : isArchived 
                                      ? 'bg-disabled' 
                                      : 'bg-primary'
                                }`}
                                style={{ width: `${getProgressPercent(proj.tracked_hours)}%` }}
                              />
                            </div>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                )
              })
            )}
          </div>
        </div>

        {/* Right Side: Manual Creator Form & Frosted AI Suggester (1/3 width) */}
        <div className="space-y-6">
          {/* Manual Add Card */}
          <div className="bg-surface-container-lowest border border-surface-container-high p-5 rounded-xl shadow-xs space-y-4">
            <div className="space-y-1">
              <h4 className="font-semibold text-headline-sm text-neutral-dark flex items-center gap-1.5">
                <Plus className="w-4 h-4 text-primary" /> Create Guideline
              </h4>
              <p className="text-text-secondary text-body-sm">
                Manually record a brand new project policy in the local database.
              </p>
            </div>

            <form onSubmit={handleManualAdd} className="space-y-3.5 pt-1">
              <div className="space-y-1">
                <label className="text-technical-sm font-semibold text-neutral-dark">Project Key / Code</label>
                <input
                  type="text"
                  placeholder="e.g., DEV-2026-M5"
                  value={newProjNumber}
                  onChange={(e) => {
                    setNewProjectNumber(e.target.value)
                    setFormError(null)
                  }}
                  className="w-full px-3 py-2 text-body-md text-neutral-dark bg-surface-container-low border border-surface-container-high rounded-lg focus:outline-none focus:border-primary placeholder:text-text-secondary/45"
                />
              </div>

              <div className="space-y-1">
                <label className="text-technical-sm font-semibold text-neutral-dark">Guideline Name</label>
                <input
                  type="text"
                  placeholder="e.g., Next Gen Platform Research"
                  value={newDescription}
                  onChange={(e) => {
                    setNewDescription(e.target.value)
                    setFormError(null)
                  }}
                  className="w-full px-3 py-2 text-body-md text-neutral-dark bg-surface-container-low border border-surface-container-high rounded-lg focus:outline-none focus:border-primary placeholder:text-text-secondary/45"
                />
              </div>

              <div className="space-y-1">
                <label className="text-technical-sm font-semibold text-neutral-dark">Work Entailment Rules</label>
                <textarea
                  rows={4}
                  placeholder="Describe tools, file types, keywords, or URL matches (e.g. VS Code, aw-webui, localhost:27180)..."
                  value={newWorkEntailment}
                  onChange={(e) => setNewWorkEntailment(e.target.value)}
                  className="w-full p-3 text-body-md text-neutral-dark bg-surface-container-low border border-surface-container-high rounded-lg focus:outline-none focus:border-primary placeholder:text-text-secondary/45 font-sans leading-relaxed"
                />
              </div>

              {formError && (
                <div className="flex items-center gap-2 p-2.5 rounded bg-danger-primary/5 border border-danger-primary/20 text-danger-primary text-body-sm font-medium">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>{formError}</span>
                </div>
              )}

              <button
                type="submit"
                disabled={savingProjects}
                className="w-full h-10 bg-primary hover:bg-primary-container text-on-primary font-medium text-action-lg px-4 rounded-lg flex items-center justify-center gap-2 transition-colors select-none cursor-pointer disabled:opacity-50"
              >
                <Plus className="w-4 h-4" /> Add Guidelines
              </button>
            </form>
          </div>

          {/* AI Project Recommender Panel (Frosted Glassmorphic Visual Polish) */}
          <div className="bg-surface-container-low/40 backdrop-blur-md border border-outline-variant/30 shadow-lg rounded-xl p-5 relative overflow-hidden transition-all duration-300 hover:shadow-primary/5 hover:border-primary/30 space-y-4">
            {/* Top halo/glowing decorative background ornament */}
            <div className="absolute top-0 right-0 -mr-6 -mt-6 w-24 h-24 bg-primary/10 rounded-full blur-xl pointer-events-none select-none" />

            <div className="space-y-1 relative z-10">
              <h4 className="font-semibold text-headline-sm text-neutral-dark flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-primary animate-pulse" /> AI Project Suggestions
              </h4>
              <p className="text-text-secondary text-body-sm leading-relaxed">
                Scan the latest 50-100 unclassified screens to auto-cluster recurring activities into formal guidelines.
              </p>
            </div>

            {suggestions.length === 0 && !loadingSuggestions && (
              <div className="space-y-4 pt-1 relative z-10">
                {suggestError ? (
                  <div className="p-3.5 rounded bg-surface-container border border-surface-container-high flex flex-col gap-1.5">
                    <strong className="text-headline-sm text-neutral-dark flex items-center gap-1.5 text-danger-primary/80">
                      <AlertCircle className="w-4 h-4" /> Cluster Analysis Alert
                    </strong>
                    <p className="text-text-secondary text-body-sm leading-relaxed">
                      {suggestError}
                    </p>
                  </div>
                ) : (
                  <div className="p-4 rounded-lg bg-surface-container-lowest/50 border border-dashed border-outline-variant/30 text-center text-text-secondary/70 text-body-sm leading-relaxed">
                    No active recommended guidelines generated yet. Click below to analyze unmapped screen history.
                  </div>
                )}

                <button
                  onClick={handleTriggerSuggestions}
                  className="w-full h-10 bg-primary/10 hover:bg-primary/20 text-primary border border-primary/20 font-medium text-action-lg px-4 rounded-lg flex items-center justify-center gap-2 transition-all select-none cursor-pointer"
                >
                  <Wand2 className="w-4 h-4" /> Recommend Guidelines
                </button>
              </div>
            )}

            {/* Glowing Loading State */}
            {loadingSuggestions && (
              <div className="py-12 flex flex-col items-center justify-center space-y-3 relative z-10 bg-surface-container-lowest/20 rounded-lg border border-dashed border-primary/30 animate-pulse-slow">
                <div className="relative">
                  <div className="w-8 h-8 rounded-full border-2 border-primary/20 border-t-primary animate-spin" />
                  <Sparkles className="w-4 h-4 text-primary absolute top-2 left-2 animate-bounce" />
                </div>
                <div className="text-center space-y-1">
                  <span className="text-neutral-dark text-headline-sm block font-semibold">
                    Clustering unclassified state...
                  </span>
                  <p className="text-text-secondary text-[11px] max-w-[200px]">
                    Evaluating window titles, active OCR layouts and descriptions...
                  </p>
                </div>
              </div>
            )}

            {/* Suggestions cards listing */}
            {suggestions.length > 0 && !loadingSuggestions && (
              <div className="space-y-3.5 pt-1 relative z-10 max-h-[480px] overflow-y-auto pr-1 scrollbar-thin">
                <div className="flex items-center justify-between text-technical-sm font-semibold text-primary pb-2 border-b border-surface-container-high">
                  <span>Found {suggestions.length} Recommendations</span>
                  <button 
                    onClick={() => setSuggestions([])}
                    className="text-text-secondary hover:text-neutral-dark text-[10px] uppercase font-bold flex items-center gap-0.5"
                  >
                    Clear <X className="w-3 h-3" />
                  </button>
                </div>

                <div className="space-y-3.5">
                  {suggestions.map((sugg, idx) => (
                    <div
                      key={idx}
                      className="p-4 rounded-lg bg-surface-container-lowest border border-outline-variant/20 shadow-xs hover:border-primary/45 transition-all duration-200 space-y-3 relative"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="bg-primary/10 text-primary font-bold text-technical-sm px-2.5 py-0.5 rounded border border-primary/20">
                          {sugg.project_number}
                        </span>
                        <span className="text-text-secondary/40 text-[10px] font-mono">#{idx + 1}</span>
                      </div>

                      <div className="space-y-1">
                        <strong className="text-neutral-dark text-headline-sm block">
                          {sugg.description}
                        </strong>
                        <p className="text-text-secondary text-body-sm leading-relaxed">
                          {sugg.work_entailment}
                        </p>
                      </div>

                      <button
                        onClick={() => handleApproveSuggestion(sugg, idx)}
                        className="w-full h-8 bg-success-green/10 hover:bg-success-green text-success-green hover:text-on-primary border border-success-green/20 text-action-md font-semibold rounded flex items-center justify-center gap-1.5 transition-all cursor-pointer"
                      >
                        <CheckCircle2 className="w-3.5 h-3.5" /> Approve & Create
                      </button>
                    </div>
                  ))}
                </div>

                <button
                  onClick={handleTriggerSuggestions}
                  className="w-full py-2 text-action-md text-text-secondary hover:text-neutral-dark bg-surface-container-high/40 hover:bg-surface-container-high rounded-lg flex items-center justify-center gap-1.5 transition-all cursor-pointer"
                >
                  <RefreshCw className="w-3.5 h-3.5" /> Re-scan / Analyze Again
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
