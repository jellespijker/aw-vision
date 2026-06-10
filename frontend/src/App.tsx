import React, { useState, useEffect, useRef } from 'react'
import axios from 'axios'

// Configure API base dynamically based on hosting port
const getApiBase = (): string => {
  if (import.meta.env.VITE_API_BASE_URL) {
    return import.meta.env.VITE_API_BASE_URL
  }
  // If hosted on a port that is not port 5666 (backend), point to port 5666
  if (window.location.port !== '5666') {
    return 'http://127.0.0.1:5666'
  }
  return ''
}

export const API_BASE = getApiBase()
axios.defaults.baseURL = API_BASE

import {
  Activity,
  Cpu,
  RefreshCw,
  Bot,
  User,
  Send,
  Info,
  Shield,
  Search,
  Image as ImageIcon,
  Maximize2,
  FileText,
  Archive,
  Save,
  X,
  Layers,
  Database,
  EyeOff,
  Sun,
  Moon,
  Compass,
  ArrowRight,
  Sparkles
} from 'lucide-react'

// Define interfaces for TypeScript safety
interface SystemLoad {
  cpu_percent: number
  memory_percent: number
}

interface DaemonStatus {
  watcher_running: boolean
  processor_running: boolean
  pending_queue_size: number
  processed_database_size: number
  processing_ids?: string[]
  system_load: SystemLoad
  aw_server_online?: boolean
  ollama_online?: boolean
  capture_cli_available?: boolean
  capture_cli_details?: {
    spectacle: boolean
    grim: boolean
  }
}

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

interface HistoryRecord {
  id: string
  timestamp: number
  image_filename: string | null
  window_title: string
  app_name: string
  is_afk: boolean
  description: string
  ocr_text: string | null
  tags: string[]
  project_number: string | null
  distance?: number
  is_processed?: boolean
  human_labeled?: boolean
  unique_things?: string | null
}

interface Project {
  project_number: string
  description: string
  work_entailment: string
  tracked_hours: number
}

interface TimelineEntry {
  label: string
  count: number
  page: number
  timestamp: number
}

export default function App() {
  // Theme and Tab States (Defaults to Light Corporate-Neutral Theme)
  const [darkMode, setDarkMode] = useState<boolean>(false)
  const [activeTab, setActiveTab] = useState<'chat' | 'gallery' | 'projects'>('chat')
  
  // API and Connection States
  const [serverOnline, setServerOnline] = useState<boolean>(true)
  const [status, setStatus] = useState<DaemonStatus | null>(null)
  const [loadingStatus, setLoadingStatus] = useState<boolean>(false)

  // Chat/Agent States
  const [agentPrompt, setAgentPrompt] = useState<string>('')
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [querying, setQuerying] = useState<boolean>(false)
  const chatLogsRef = useRef<HTMLDivElement>(null)

  // Gallery/Search States
  const [searchQuery, setSearchQuery] = useState<string>('')
  const [loadingHistory, setLoadingHistory] = useState<boolean>(false)
  const [historyRecords, setHistoryRecords] = useState<HistoryRecord[]>([])
  const [currentPage, setCurrentPage] = useState<number>(1)
  const [totalPages, setTotalPages] = useState<number>(1)
  const [totalCount, setTotalCount] = useState<number>(0)
  const [timelineEntries, setTimelineEntries] = useState<TimelineEntry[]>([])
  const [pageSize] = useState<number>(30)
  const [selectedRecord, setSelectedRecord] = useState<HistoryRecord | null>(null)
  const [lightboxOpen, setLightboxOpen] = useState<boolean>(false)
  const [expandedOcrCardId, setExpandedOcrCardId] = useState<string | null>(null)
  const [processingIds, setProcessingIds] = useState<string[]>([])
  const [bulkProcessing, setBulkProcessing] = useState<boolean>(false)
  const [reprocessOcr, setReprocessOcr] = useState<boolean>(false)
  const [reprocessRange, setReprocessRange] = useState<string>('last10')
  const [reprocessing, setReprocessing] = useState<boolean>(false)

  const [cardViewFull, setCardViewFull] = useState<Record<string, boolean>>({})
  const [lightboxViewFull, setLightboxViewFull] = useState<boolean>(false)
  const [logs, setLogs] = useState<Record<string, string[]>>({})
  const pollingIntervals = useRef<Record<string, any>>({})


  // Projects States
  const [projectsList, setProjectsList] = useState<Project[]>([])
  const [projectsJsonInput, setProjectsJsonInput] = useState<string>('[]')
  const [savingProjects, setSavingProjects] = useState<boolean>(false)
  const [toastMessage, setToastMessage] = useState<{ text: string; type: 'success' | 'danger' } | null>(null)

  // Check backend server connection and poll status
  useEffect(() => {
    checkServerStatus()
    const timer = setInterval(getDaemonStatus, 5000)
    return () => clearInterval(timer)
  }, [serverOnline])

  // Poll history records if there are pending items in the queue to update live
  useEffect(() => {
    if (status && status.pending_queue_size > 0) {
      const timer = setInterval(() => {
        fetchHistory(currentPage)
      }, 10000)
      return () => clearInterval(timer)
    }
  }, [status, searchQuery, currentPage])

  // Synchronize processingIds with backend status.processing_ids
  useEffect(() => {
    if (status && status.processing_ids) {
      setProcessingIds(prev => {
        const backendIds = status.processing_ids || []
        const finishedIds = prev.filter(id => !backendIds.includes(id))
        
        finishedIds.forEach(id => {
          if (pollingIntervals.current[id]) {
            clearInterval(pollingIntervals.current[id])
            delete pollingIntervals.current[id]
          }
        })

        if (finishedIds.length > 0) {
          setTimeout(() => {
            fetchHistory(currentPage)
          }, 500)
        }

        return backendIds
      })
    }
  }, [status])

  // Automatically update the active Lightbox record when the gallery history refreshes
  useEffect(() => {
    if (selectedRecord && historyRecords.length > 0) {
      const match = historyRecords.find(r => r.id === selectedRecord.id)
      if (match && JSON.stringify(match) !== JSON.stringify(selectedRecord)) {
        setSelectedRecord(match)
      }
    }
  }, [historyRecords, selectedRecord])

  // Scroll chat window to bottom on updates
  useEffect(() => {
    if (chatLogsRef.current) {
      chatLogsRef.current.scrollTop = chatLogsRef.current.scrollHeight
    }
  }, [chatMessages, querying])

  // Helper toast notification auto-dismissal
  useEffect(() => {
    if (toastMessage) {
      const t = setTimeout(() => setToastMessage(null), 4000)
      return () => clearTimeout(t)
    }
  }, [toastMessage])

  // Methods
  const checkServerStatus = async () => {
    setLoadingStatus(true)
    try {
      const resp = await axios.get('/api/status', { timeout: 2000 })
      if (resp.status === 200) {
        setServerOnline(true)
        setStatus(resp.data)
        fetchHistory(1)
        fetchProjects()
      }
    } catch (e) {
      setServerOnline(false)
    } finally {
      setLoadingStatus(false)
    }
  }

  const getDaemonStatus = async () => {
    if (!serverOnline) return
    try {
      const resp = await axios.get('/api/status', { timeout: 1500 })
      if (resp.status === 200) {
        setStatus(resp.data)
      }
    } catch (e) {
      setServerOnline(false)
    }
  }

  const fetchHistory = async (page: number = 1, queryOverride?: string) => {
    if (!serverOnline) return
    setLoadingHistory(true)
    try {
      const q = queryOverride !== undefined ? queryOverride : searchQuery
      let url = `/api/history?page=${page}&limit=${pageSize}`
      if (q && q.trim()) {
        url += `&search=${encodeURIComponent(q.trim())}`
      }
      const resp = await axios.get(url)
      setHistoryRecords(resp.data.items || [])
      setTotalCount(resp.data.total || 0)
      setCurrentPage(resp.data.page || 1)
      setTotalPages(resp.data.total_pages || 1)
      setTimelineEntries(resp.data.timeline || [])
    } catch (e) {
      console.error('Error loading screenshot history', e)
    } finally {
      setLoadingHistory(false)
    }
  }

  const clearSearch = () => {
    setSearchQuery('')
    fetchHistory(1, '')
  }

  const handleForceProcess = async (fileId: string): Promise<HistoryRecord | null> => {
    if (!serverOnline) return null
    setProcessingIds(prev => [...prev, fileId])

    const pollLogs = async () => {
      try {
        const resp = await axios.get(`/api/process/${fileId}/logs`)
        if (resp.data && resp.data.logs) {
          setLogs(prev => ({ ...prev, [fileId]: resp.data.logs }))
        }
      } catch (err) {
        console.error("Error polling logs:", err)
      }
    }

    // Start polling immediately and then every 1000ms
    pollLogs()
    const interval = setInterval(pollLogs, 1000)
    pollingIntervals.current[fileId] = interval

    try {
      const resp = await axios.post(`/api/process/${fileId}`)
      if (resp.status === 200) {
        setToastMessage({ text: 'Screenshot processed successfully!', type: 'success' })
        fetchHistory(currentPage)
        getDaemonStatus()
        
        // Also update selectedRecord if it's currently selected in lightbox
        if (selectedRecord && selectedRecord.id === fileId) {
          setSelectedRecord(resp.data as HistoryRecord)
        }
        
        return resp.data as HistoryRecord
      }
    } catch (e: any) {
      const errMsg = e.response?.data?.detail || e.message || 'Error occurred'
      setToastMessage({ text: `Failed to process screenshot: ${errMsg}`, type: 'danger' })
    } finally {
      setProcessingIds(prev => prev.filter(id => id !== fileId))
      if (pollingIntervals.current[fileId]) {
        clearInterval(pollingIntervals.current[fileId])
        delete pollingIntervals.current[fileId]
      }
      // One final logs poll to get completion details
      setTimeout(pollLogs, 500)
    }
    return null
  }

  const handleProcessAll = async () => {
    if (!serverOnline) return
    setBulkProcessing(true)
    try {
      const resp = await axios.post('/api/process-all')
      if (resp.data.status === 'success') {
        setToastMessage({ text: 'Bulk processing triggered in background.', type: 'success' })
        getDaemonStatus()
        fetchHistory(currentPage)
      }
    } catch (e: any) {
      const errMsg = e.response?.data?.detail || e.message || 'Error occurred'
      setToastMessage({ text: `Failed to start bulk processing: ${errMsg}`, type: 'danger' })
    } finally {
      setBulkProcessing(false)
    }
  }

  const handleReprocessSnapshots = async (options: {
    ids?: string[]
    limit?: number
    startTime?: number
    endTime?: number
    all?: boolean
    reprocessOcr?: boolean
  }): Promise<boolean> => {
    if (!serverOnline) return false

    const { ids, limit, startTime, endTime, all, reprocessOcr = false } = options
    const targetId = ids && ids.length === 1 ? ids[0] : null

    if (targetId) {
      setProcessingIds(prev => Array.from(new Set([...prev, targetId])))
    } else {
      setReprocessing(true)
    }

    const pollLogs = async () => {
      if (!targetId) return
      try {
        const resp = await axios.get(`/api/process/${targetId}/logs`)
        if (resp.data && resp.data.logs) {
          setLogs(prev => ({ ...prev, [targetId]: resp.data.logs }))
        }
      } catch (err) {
        console.error("Error polling logs:", err)
      }
    }

    let interval: any = null
    if (targetId) {
      pollLogs()
      interval = setInterval(pollLogs, 1000)
      pollingIntervals.current[targetId] = interval
    }

    try {
      const payload: any = { reprocess_ocr: reprocessOcr }
      if (ids) payload.ids = ids
      if (limit) payload.limit = limit
      if (startTime !== undefined) payload.start_time = startTime
      if (endTime !== undefined) payload.end_time = endTime
      if (all !== undefined) payload.all = all

      const resp = await axios.post('/api/reprocess', payload)

      if (resp.status === 200) {
        setToastMessage({ text: resp.data.message || 'Reprocessing triggered successfully!', type: 'success' })
        getDaemonStatus()
        
        // Wait briefly and refresh
        setTimeout(() => {
          fetchHistory(currentPage)
        }, 1500)
        
        return true
      }
    } catch (e: any) {
      const errMsg = e.response?.data?.detail || e.message || 'Error occurred'
      setToastMessage({ text: `Failed to reprocess: ${errMsg}`, type: 'danger' })
    } finally {
      if (!targetId) {
        setReprocessing(false)
      } else {
        // Set safety timeout to clear the single-item processing state if it gets stuck
        setTimeout(() => {
          if (pollingIntervals.current[targetId]) {
            clearInterval(pollingIntervals.current[targetId])
            delete pollingIntervals.current[targetId]
          }
          setProcessingIds(prev => prev.filter(id => id !== targetId))
          fetchHistory(currentPage)
        }, 45000)
      }
    }
    return false
  }

  const handleBulkReprocessSidebar = async () => {
    let options: any = { reprocessOcr }
    
    if (reprocessRange === 'all') {
      options.all = true
    } else if (reprocessRange === 'last10') {
      options.limit = 10
    } else if (reprocessRange === 'last50') {
      options.limit = 50
    } else if (reprocessRange === 'today') {
      const start = new Date()
      start.setHours(0, 0, 0, 0)
      options.startTime = start.getTime() / 1000
      options.endTime = Date.now() / 1000
    } else if (reprocessRange === 'last24h') {
      options.startTime = (Date.now() - 24 * 60 * 60 * 1000) / 1000
      options.endTime = Date.now() / 1000
    }

    await handleReprocessSnapshots(options)
  }

  const fetchProjects = async () => {
    if (!serverOnline) return
    try {
      const resp = await axios.get('/api/projects')
      setProjectsList(resp.data.projects)
      const rawList = resp.data.projects.filter((p: Project) => p.project_number !== 'Unclassified')
      setProjectsJsonInput(JSON.stringify(rawList, null, 2))
    } catch (e) {
      console.error('Error loading projects list', e)
    }
  }

  const saveProjectsJson = async () => {
    if (!serverOnline) return
    setSavingProjects(true)
    try {
      const parsed = JSON.parse(projectsJsonInput)
      const resp = await axios.post('/api/projects', parsed)
      if (resp.data.status === 'success') {
        setToastMessage({ text: 'Successfully updated project guidelines.', type: 'success' })
        fetchProjects()
      }
    } catch (e: any) {
      setToastMessage({ text: `Failed to save: Invalid JSON or API error. (${e.message})`, type: 'danger' })
    } finally {
      setSavingProjects(false)
    }
  }

  const handleUpdateLabel = async (recordId: string, projectNumber: string | null) => {
    if (!serverOnline) return
    try {
      const resp = await axios.post(`/api/snapshots/${recordId}/label`, {
        project_number: projectNumber
      })
      if (resp.status === 200) {
        setToastMessage({ text: 'Project label updated successfully!', type: 'success' })
        
        // Update in-place to avoid page refresh or scroll reset
        setHistoryRecords(prev => prev.map(rec => {
          if (rec.id === recordId) {
            return {
              ...rec,
              project_number: projectNumber,
              human_labeled: true
            }
          }
          return rec
        }))

        // Also update selectedRecord if it's currently selected in lightbox
        setSelectedRecord(prev => {
          if (prev && prev.id === recordId) {
            return {
              ...prev,
              project_number: projectNumber,
              human_labeled: true
            }
          }
          return prev
        })

        // Refresh project list to update tracked_hours breakdown
        fetchProjects()
      }
    } catch (e: any) {
      const errMsg = e.response?.data?.detail || e.message || 'Error occurred'
      setToastMessage({ text: `Failed to update project label: ${errMsg}`, type: 'danger' })
    }
  }

  const submitAgentQuery = async (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    if (!agentPrompt.trim() || querying) return

    const userPrompt = agentPrompt.trim()
    setAgentPrompt('')
    
    const updatedHistory = [...chatMessages, { role: 'user', content: userPrompt } as ChatMessage]
    setChatMessages(updatedHistory)
    setQuerying(true)

    try {
      const resp = await axios.post('/api/query', {
        prompt: userPrompt,
        history: chatMessages
      })
      if (resp.status === 200) {
        setChatMessages([...updatedHistory, { role: 'assistant', content: resp.data.response }])
      }
    } catch (e: any) {
      setChatMessages([
        ...updatedHistory,
        {
          role: 'assistant',
          content: `Failed to receive answer from agent. Make sure Ollama model is loaded correctly. Error: ${e.message}`
        }
      ])
    } finally {
      setQuerying(false)
    }
  }

  const openImageLightbox = async (rec: HistoryRecord) => {
    setSelectedRecord(rec)
    setLightboxViewFull(false)
    setLightboxOpen(true)

    // Retrieve processing logs (whether pending or processed, falling back to disk)
    try {
      const resp = await axios.get(`/api/process/${rec.id}/logs`)
      if (resp.data && resp.data.logs) {
        setLogs(prev => ({ ...prev, [rec.id]: resp.data.logs }))
      }
    } catch (err) {
      console.error("Error loading processing logs for record:", err)
    }
  }

  const formatTimestamp = (ts: number) => {
    if (!ts) return ''
    const d = new Date(ts * 1000)
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  }

  const getPageRange = () => {
    let startPage = Math.max(1, currentPage - 2)
    let endPage = Math.min(totalPages, startPage + 4)
    if (endPage - startPage < 4) {
      startPage = Math.max(1, endPage - 4)
    }
    const range = []
    for (let i = startPage; i <= endPage; i++) {
      range.push(i)
    }
    return range
  }

  const getProgressPercent = (hours: number) => {
    if (!hours) return 0
    const maxTracked = Math.max(...projectsList.map(p => p.tracked_hours || 0), 10)
    return Math.min(100, (hours / maxTracked) * 100)
  }

  // Premium Custom Inline Markdown & Citation Parser (No raw HTML, 100% React XSS-Safe)
  const renderMessageContent = (text: string) => {
    if (!text) return null
    
    // Split text by code blocks first
    const parts = text.split(/(```[\s\S]*?```)/g)
    
    return parts.map((part, index) => {
      // Is code block?
      if (part.startsWith('```') && part.endsWith('```')) {
        const match = part.match(/```(\w*)\n([\s\S]*?)```/)
        const lang = match ? match[1] : ''
        const code = match ? match[2] : part.slice(3, -3)
        return (
          <pre key={index} className="bg-surface-container text-neutral-dark p-4 rounded my-3 text-technical-sm overflow-x-auto border border-surface-container-high">
            {lang && <div className="text-[10px] text-text-secondary font-messina font-semibold uppercase tracking-wider mb-2 border-b border-surface-container-high pb-1">{lang}</div>}
            <code className="block whitespace-pre select-all font-mono">{code}</code>
          </pre>
        )
      }

      // Format lines, handling Bold, Inline Code, and Screenshot Citations
      const lines = part.split('\n')
      return lines.map((line, lIdx) => {
        const regex = /(\*\*.*?\*\*|`.*?`|Screenshot:\s*[a-f0-9-_\d]+\.png)/gi
        const tokens = line.split(regex)
        
        const lineElements = tokens.map((token, tIdx) => {
          if (token.startsWith('**') && token.endsWith('**')) {
            return (
              <strong key={tIdx} className="font-semibold text-neutral-dark">
                {token.slice(2, -2)}
              </strong>
            )
          }
          if (token.startsWith('`') && token.endsWith('`')) {
            return (
              <code key={tIdx} className="bg-surface-container-low text-danger-primary px-1.5 py-0.5 rounded font-mono text-technical-sm border border-surface-container">
                {token.slice(1, -1)}
              </code>
            )
          }
          if (/^Screenshot:\s*([a-f0-9-_\d]+\.png)$/i.test(token.trim())) {
            const filename = token.replace(/^Screenshot:\s*/i, '').trim()
            return (
              <div
                key={tIdx}
                onClick={() => {
                  const rec = historyRecords.find(r => r.image_filename === filename) || {
                    id: Math.random().toString(),
                    timestamp: Date.now() / 1000,
                    image_filename: filename,
                    window_title: filename,
                    app_name: 'Screenshot Citation',
                    is_afk: false,
                    description: 'Direct screenshot citation from conversational agent response.',
                    ocr_text: null,
                    tags: [],
                    project_number: null,
                    unique_things: null
                  }
                  openImageLightbox(rec)
                }}
                className="inline-flex flex-col p-1 bg-surface-container-lowest border border-surface-container-high rounded mx-1 hover:border-primary-container transition-all cursor-pointer align-middle max-w-[120px]"
              >
                <img src={`${API_BASE}/api/screenshots/${filename}`} className="w-full h-auto rounded object-cover max-h-[60px]" alt="Thumbnail" />
                <span className="block text-[9px] text-text-secondary text-center truncate mt-1 font-mono">{filename.substring(0, 8)}...</span>
              </div>
            )
          }
          return token
        })

        return (
          <p key={lIdx} className={`leading-relaxed text-body-md ${lIdx === lines.length - 1 ? 'mb-0' : 'mb-2'}`}>
            {lineElements}
          </p>
        )
      })
    })
  }

  return (
    <div className={`min-h-screen ${
      darkMode 
        ? 'bg-inverse-surface text-inverse-on-surface' 
        : 'bg-surface text-on-surface'
    }`}>
      
      <div className="max-w-7xl mx-auto px-6 py-6 lg:px-8">
        
        {/* Toast Alerts Notification banner (Flat UI / Precise signaling) */}
        {toastMessage && (
          <div className={`fixed top-5 right-5 z-50 p-4 rounded border text-white font-messina text-action-md flex items-center gap-3 ${
            toastMessage.type === 'success' 
              ? 'bg-secondary border-secondary' 
              : 'bg-danger-primary border-danger-primary'
          }`}>
            <span className="font-semibold">{toastMessage.text}</span>
          </div>
        )}

        {/* Server Offline Warning Card (Flat Red Border / Light Red Surface) */}
        {!serverOnline && (
          <div className="bg-danger-surface border-danger-primary p-5 rounded border mb-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
            <div className="space-y-1">
              <h3 className="text-danger-primary font-semibold text-headline-sm flex items-center gap-2">
                <EyeOff className="w-5 h-5" /> aw-vision Backend is Offline
              </h3>
              <p className="text-neutral-dark text-body-sm">
                To start the local screen capture ingestion loops and semantic recollecting API, execute the following command in your terminal inside the <code className="text-danger-primary bg-white px-1.5 py-0.5 rounded text-technical-sm border border-danger-primary/30">aw-vision</code> workspace:
              </p>
              <pre className="bg-white text-danger-primary p-2.5 rounded border border-danger-primary/25 text-technical-sm font-mono select-all inline-block mt-2">
                poetry run uvicorn aw_vision.server:app --port 5666 --reload
              </pre>
            </div>
            <button
              onClick={checkServerStatus}
              disabled={loadingStatus}
              className="bg-danger-primary hover:bg-danger-hover active:bg-danger-active text-white text-action-md font-medium h-10 px-5 rounded flex items-center gap-2 transition-colors disabled:opacity-50 select-none shrink-0"
            >
              <RefreshCw className={`w-4 h-4 ${loadingStatus ? 'animate-spin' : ''}`} />
              Retry Connection
            </button>
          </div>
        )}

        {/* Header Section */}
        <header className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8 pb-6 border-b border-surface-container-high">
          <div>
            <div className="flex items-center gap-2.5 mb-1.5">
              <Layers className={`w-7 h-7 ${darkMode ? 'text-inverse-primary' : 'text-primary-container'}`} />
              <h1 className="text-2xl font-semibold tracking-tight font-sans text-neutral-dark">
                Visual &amp; Semantic Memory
              </h1>
            </div>
            <p className="text-text-secondary text-body-sm max-w-2xl">
              Secure, local-first computer history pipeline. Screenshot capture loops, optical text models, and vector embeddings stored completely on-device.
            </p>
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            {/* Theme Toggle Button (Messina action height 40px) */}
            <button 
              onClick={() => setDarkMode(!darkMode)}
              className="h-10 w-10 rounded border border-surface-container-high hover:bg-surface-container-low text-text-secondary transition-colors flex items-center justify-center select-none"
              title={darkMode ? "Switch to Light Theme" : "Switch to Dark Theme"}
            >
              {darkMode ? <Sun className="w-4 h-4 text-attention-yellow" /> : <Moon className="w-4 h-4 text-primary" />}
            </button>

            {serverOnline && status && (
              <>
                {/* Active Daemon Indicators (Pill shape reserved exclusively for Status Badges) */}
                <div className="bg-surface-container-low border border-surface-container-high px-3 h-10 rounded-full flex items-center gap-2 text-indicator-bold text-neutral-dark" title="aw-watcher activity status">
                  <span className={`w-2.5 h-2.5 rounded-full ${status.watcher_running ? 'bg-success-green' : 'bg-danger-primary'}`}></span>
                  <span>Watcher: {status.watcher_running ? 'ACTIVE' : 'STOPPED'}</span>
                </div>

                <div className="bg-surface-container-low border border-surface-container-high px-3 h-10 rounded-full flex items-center gap-2 text-indicator-bold text-neutral-dark" title="Bulk processor status">
                  <span className={`w-2.5 h-2.5 rounded-full ${status.processor_running ? 'bg-success-green animate-pulse-slow' : 'bg-disabled'}`}></span>
                  <span>Processor: {status.processor_running ? 'ACTIVE' : 'IDLE'}</span>
                </div>

                <div className="bg-surface-container-low border border-surface-container-high px-3 h-10 rounded-full flex items-center gap-2 text-indicator-bold text-neutral-dark" title="ActivityWatch core server connection status (port 5600)">
                  <span className={`w-2.5 h-2.5 rounded-full ${status.aw_server_online ? 'bg-success-green' : 'bg-danger-primary'}`}></span>
                  <span>aw-server: {status.aw_server_online ? 'ONLINE' : 'OFFLINE'}</span>
                </div>

                <div className="bg-surface-container-low border border-surface-container-high px-3 h-10 rounded-full flex items-center gap-2 text-indicator-bold text-neutral-dark" title="Ollama API service connection status (port 11434)">
                  <span className={`w-2.5 h-2.5 rounded-full ${status.ollama_online ? 'bg-success-green' : 'bg-danger-primary'}`}></span>
                  <span>Ollama: {status.ollama_online ? 'ONLINE' : 'OFFLINE'}</span>
                </div>

                <div className="bg-surface-container-low border border-surface-container-high px-3 h-10 rounded-full flex items-center gap-2 text-indicator-bold text-neutral-dark" title="Wayland capture utility spectacle/grim availability">
                  <span className={`w-2.5 h-2.5 rounded-full ${status.capture_cli_available ? 'bg-success-green' : 'bg-danger-primary'}`}></span>
                  <span>Capture CLI: {status.capture_cli_available ? 'AVAILABLE' : 'MISSING'}</span>
                </div>

                <button
                  onClick={checkServerStatus}
                  className="h-10 w-10 rounded border border-surface-container-high bg-surface-container-lowest hover:bg-surface-container-low text-text-secondary transition-colors flex items-center justify-center select-none"
                >
                  <RefreshCw className="w-4 h-4" />
                </button>
              </>
            )}
          </div>
        </header>

        {serverOnline && (
          <>
            {/* Tabs Navigation (Height 40px, font Messina Sans) */}
            <div className="flex border-b border-surface-container-high mb-6 gap-2">
              <button
                id="tab-chat"
                onClick={() => setActiveTab('chat')}
                className={`h-10 px-5 text-action-md font-medium rounded-t transition-colors border-b-2 flex items-center gap-2 font-messina select-none ${
                  activeTab === 'chat'
                    ? 'border-primary-container text-primary-container bg-surface-container-lowest'
                    : 'border-transparent text-text-secondary hover:text-neutral-dark hover:bg-surface-container-low'
                }`}
              >
                <Bot className="w-4 h-4" /> Ask Memory Agent
              </button>
              <button
                id="tab-gallery"
                onClick={() => setActiveTab('gallery')}
                className={`h-10 px-5 text-action-md font-medium rounded-t transition-colors border-b-2 flex items-center gap-2 font-messina select-none ${
                  activeTab === 'gallery'
                    ? 'border-primary-container text-primary-container bg-surface-container-lowest'
                    : 'border-transparent text-text-secondary hover:text-neutral-dark hover:bg-surface-container-low'
                }`}
              >
                <ImageIcon className="w-4 h-4" /> Screenshot Library &amp; Search {totalCount > 0 && `(${totalCount})`}
              </button>
              <button
                id="tab-projects"
                onClick={() => setActiveTab('projects')}
                className={`h-10 px-5 text-action-md font-medium rounded-t transition-colors border-b-2 flex items-center gap-2 font-messina select-none ${
                  activeTab === 'projects'
                    ? 'border-primary-container text-primary-container bg-surface-container-lowest'
                    : 'border-transparent text-text-secondary hover:text-neutral-dark hover:bg-surface-container-low'
                }`}
              >
                <FileText className="w-4 h-4" /> Project Mapping Dashboard
              </button>
            </div>

            {/* TAB 1: ASK MEMORY AGENT */}
            {activeTab === 'chat' && (
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                
                {/* Chat Panel */}
                <div className="lg:col-span-2 flex flex-col h-[650px] rounded-lg border border-surface-container-high bg-surface-container-lowest">
                  <div className="p-4 bg-surface-container-low border-b border-surface-container-high flex items-center gap-3">
                    <div className="w-10 h-10 rounded bg-surface-container border border-surface-container-high text-primary-container flex items-center justify-center">
                      <Bot className="w-5 h-5" />
                    </div>
                    <div>
                      <h3 className="font-semibold text-headline-sm text-neutral-dark">LangGraph ReAct Assistant</h3>
                      <p className="text-text-secondary text-body-sm">Converses, searches OCR codes, tracks hours, and queries historical sessions.</p>
                    </div>
                  </div>

                  {/* Chat Message Stream */}
                  <div ref={chatLogsRef} className="flex-1 overflow-y-auto p-4 space-y-4 bg-surface-dim">
                    {chatMessages.length === 0 ? (
                      <div className="h-full flex flex-col items-center justify-center text-center p-6 space-y-4">
                        <div className="w-12 h-12 rounded bg-surface-container text-primary-container flex items-center justify-center border border-surface-container-high">
                          <Bot className="w-6 h-6" />
                        </div>
                        <h4 className="font-semibold text-headline-sm text-neutral-dark">Ask anything about your past computer activity</h4>
                        <p className="text-text-secondary text-body-sm max-w-md leading-relaxed">
                          The local AI Agent can traverse metadata tags, full screenshots, OCR logs, and ActivityWatch window state. Try clicking a shortcut below:
                        </p>
                        
                        {/* Prompt Suggestions */}
                        <div className="flex flex-col gap-2 max-w-md w-full pt-2">
                          <button
                            onClick={() => setAgentPrompt('Which files or repositories was I editing yesterday?')}
                            className="text-left text-action-md font-messina font-medium bg-surface-container-lowest border border-surface-container-high hover:border-primary-container hover:bg-surface-container-low h-10 px-4 rounded text-neutral-dark transition-colors flex items-center gap-2 group select-none"
                          >
                            <Compass className="w-3.5 h-3.5 text-primary-container shrink-0" />
                            <span>"Which files or repos was I editing yesterday?"</span>
                            <ArrowRight className="w-3 h-3 text-text-secondary ml-auto opacity-0 group-hover:opacity-100 group-hover:translate-x-0.5 transition-all" />
                          </button>

                          <button
                            onClick={() => setAgentPrompt('A couple of days ago I was browsing the web for sneakers, can you tell me which site had the purple sneakers?')}
                            className="text-left text-action-md font-messina font-medium bg-surface-container-lowest border border-surface-container-high hover:border-primary-container hover:bg-surface-container-low h-10 px-4 rounded text-neutral-dark transition-colors flex items-center gap-2 group select-none"
                          >
                            <Compass className="w-3.5 h-3.5 text-primary-container shrink-0" />
                            <span>"Which site had the purple sneakers?"</span>
                            <ArrowRight className="w-3 h-3 text-text-secondary ml-auto opacity-0 group-hover:opacity-100 group-hover:translate-x-0.5 transition-all" />
                          </button>

                          <button
                            onClick={() => setAgentPrompt('How much time did I spend on project PRJ-2026-042 today?')}
                            className="text-left text-action-md font-messina font-medium bg-surface-container-lowest border border-surface-container-high hover:border-primary-container hover:bg-surface-container-low h-10 px-4 rounded text-neutral-dark transition-colors flex items-center gap-2 group select-none"
                          >
                            <Compass className="w-3.5 h-3.5 text-primary-container shrink-0" />
                            <span>"How much time did I spend on PRJ-2026-042?"</span>
                            <ArrowRight className="w-3 h-3 text-text-secondary ml-auto opacity-0 group-hover:opacity-100 group-hover:translate-x-0.5 transition-all" />
                          </button>
                        </div>
                      </div>
                    ) : (
                      chatMessages.map((msg, index) => (
                        <div key={index} className={`flex gap-3 max-w-[85%] ${msg.role === 'user' ? 'ml-auto flex-row-reverse' : 'mr-auto'}`}>
                          <div className={`w-8 h-8 rounded flex items-center justify-center shrink-0 border ${
                            msg.role === 'user' 
                              ? 'bg-primary-container border-primary-container text-white' 
                              : 'bg-surface-container-low border-surface-container-high text-neutral-dark'
                          }`}>
                            {msg.role === 'user' ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
                          </div>
                          <div className={`p-3.5 rounded border text-body-md ${
                            msg.role === 'user'
                              ? 'bg-primary-container border-primary-container text-white'
                              : 'bg-surface-container-lowest border-surface-container-high text-neutral-dark'
                          }`}>
                            <div className="text-[10px] font-semibold font-messina opacity-60 tracking-wider uppercase mb-1">{msg.role === 'user' ? 'You' : 'Agent Assistant'}</div>
                            <div className="space-y-2">{renderMessageContent(msg.content)}</div>
                          </div>
                        </div>
                      ))
                    )}

                    {/* Agent Thinking Loader */}
                    {querying && (
                      <div className="flex gap-3 max-w-[80%] mr-auto items-start">
                        <div className="w-8 h-8 rounded bg-surface-container border border-surface-container-high text-text-secondary flex items-center justify-center shrink-0">
                          <Bot className="w-4 h-4 animate-spin" />
                        </div>
                        <div className="p-3.5 rounded bg-surface-container-lowest border border-surface-container-high text-body-sm text-text-secondary flex items-center gap-3">
                          <div className="flex space-x-1">
                            <span className="w-2 h-2 rounded-full bg-primary-container animate-bounce" style={{ animationDelay: '0ms' }}></span>
                            <span className="w-2 h-2 rounded-full bg-primary-container animate-bounce" style={{ animationDelay: '150ms' }}></span>
                            <span className="w-2 h-2 rounded-full bg-primary-container animate-bounce" style={{ animationDelay: '300ms' }}></span>
                          </div>
                          <span>Executing local tools and model reasoning...</span>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Chat Input form */}
                  <div className="p-4 border-t border-surface-container-high bg-surface-container-low">
                    <form onSubmit={submitAgentQuery} className="flex gap-2">
                      <input
                        type="text"
                        value={agentPrompt}
                        onChange={(e) => setAgentPrompt(e.target.value)}
                        placeholder="Ask a question about your screen history, codes, or active projects..."
                        className="flex-1 rounded h-10 px-4 text-body-md bg-white border border-surface-container-high text-on-surface focus:outline-none focus:border-primary-container"
                        disabled={querying}
                      />
                      <button
                        type="submit"
                        disabled={querying || !agentPrompt.trim()}
                        className="bg-primary-container hover:bg-primary text-white rounded w-10 h-10 flex items-center justify-center transition-colors disabled:opacity-50 shrink-0 select-none"
                      >
                        {querying ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                      </button>
                    </form>
                  </div>
                </div>

                {/* Queue Stats Side panel */}
                <div className="space-y-6">
                  {status && (
                    <div className="bg-surface-container-lowest border border-surface-container-high p-5 rounded-lg">
                    <h3 className="font-semibold text-headline-sm text-neutral-dark mb-4 flex items-center gap-2">
                      <Database className="w-4 h-4 text-primary-container" /> System Pipeline Queue
                    </h3>

                    <div className="space-y-4">
                      <div className="flex justify-between items-center text-body-sm">
                        <span className="text-text-secondary font-medium">Screenshots Pending</span>
                        {/* Status indicators are pill rounded-full */}
                        <span className="px-2.5 py-1 bg-warning-light text-neutral-dark rounded-full text-indicator-bold border border-attention-yellow/30">
                          {status.pending_queue_size}
                        </span>
                      </div>
                      
                      <div className="flex justify-between items-center text-body-sm">
                        <span className="text-text-secondary font-medium">Screenshots Indexed</span>
                        {/* Status indicators are pill rounded-full */}
                        <span className="px-2.5 py-1 bg-surface-container-low text-neutral-dark rounded-full text-indicator-bold border border-surface-container-high">
                          {status.processed_database_size}
                        </span>
                      </div>

                      <div className="pt-2">
                        <div className="w-full h-2 bg-surface-container rounded-full overflow-hidden">
                          <div
                            className="h-full bg-primary-container rounded-full transition-all duration-500"
                            style={{ width: `${(status.processed_database_size / (status.processed_database_size + status.pending_queue_size || 1)) * 100}%` }}
                          ></div>
                        </div>
                      </div>

                      {status.pending_queue_size > 0 && (
                        <button
                          type="button"
                          onClick={handleProcessAll}
                          disabled={bulkProcessing}
                          className="w-full bg-accent-surface hover:bg-surface-container text-primary text-action-md font-semibold py-2 px-3 rounded border border-primary/20 transition-colors select-none flex items-center justify-center gap-2 cursor-pointer"
                        >
                          <Cpu className={`w-4 h-4 ${bulkProcessing ? 'animate-spin' : ''}`} />
                          Force Process All Queue
                        </button>
                      )}

                      {status.system_load && (
                        <div className="grid grid-cols-2 gap-3 pt-3 border-t border-surface-container text-technical-sm">
                          <div className="space-y-1 p-2 bg-surface-container-low rounded border border-surface-container-high">
                            <span className="text-text-secondary">Host CPU</span>
                            <div className="font-semibold text-neutral-dark flex items-center gap-1">
                              <Cpu className="w-3.5 h-3.5 text-primary-container" /> {status.system_load.cpu_percent}%
                            </div>
                          </div>
                          <div className="space-y-1 p-2 bg-surface-container-low rounded border border-surface-container-high">
                            <span className="text-text-secondary">Host RAM</span>
                            <div className="font-semibold text-neutral-dark flex items-center gap-1">
                              <Activity className="w-3.5 h-3.5 text-primary" /> {status.system_load.memory_percent}%
                            </div>
                          </div>
                        </div>
                      )}

                      <div className="p-3 bg-surface-container-low rounded border border-surface-container-high text-body-sm text-text-secondary flex items-start gap-2 leading-relaxed">
                        <Info className="w-4 h-4 text-primary-container shrink-0 mt-0.5" />
                        <div>
                          <strong className="text-neutral-dark">Resource Saving Queue:</strong> Screenshots are batched and processed ONLY when system CPU is low to avoid gaming or build disruption.
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* Database Reprocessing Controls */}
                {status && (
                  <div className="bg-surface-container-lowest border border-surface-container-high p-5 rounded-lg">
                    <h3 className="font-semibold text-headline-sm text-neutral-dark mb-4 flex items-center gap-2">
                      <RefreshCw className="w-4 h-4 text-primary-container" /> Reprocess History
                    </h3>

                    <div className="space-y-4 font-messina">
                      <div className="space-y-1.5">
                        <label className="text-body-sm font-semibold text-text-secondary">Range to Reprocess</label>
                        <select
                          value={reprocessRange}
                          onChange={(e) => setReprocessRange(e.target.value)}
                          className="w-full bg-surface-container-low border border-surface-container-high h-10 px-3 rounded text-body-md text-neutral-dark outline-none cursor-pointer hover:border-primary-container transition-colors"
                        >
                          <option value="last10">Latest 10 Snapshots</option>
                          <option value="last50">Latest 50 Snapshots</option>
                          <option value="today">Today's Sessions</option>
                          <option value="last24h">Past 24 Hours</option>
                          <option value="all">Entire Database (OCR cached)</option>
                        </select>
                      </div>

                      <div className="flex items-center gap-2.5 py-1 select-none">
                        <input
                          type="checkbox"
                          id="reprocessOcrCheckbox"
                          checked={reprocessOcr}
                          onChange={(e) => setReprocessOcr(e.target.checked)}
                          className="w-4 h-4 rounded border-surface-container-high text-primary focus:ring-primary cursor-pointer"
                        />
                        <label htmlFor="reprocessOcrCheckbox" className="text-body-sm font-medium text-neutral-dark cursor-pointer">
                          Include OCR Sweep (Slow)
                        </label>
                      </div>

                      <button
                        type="button"
                        onClick={handleBulkReprocessSidebar}
                        disabled={reprocessing || bulkProcessing}
                        className="w-full bg-neutral-dark hover:bg-neutral text-white text-action-md font-semibold h-10 rounded border border-neutral-dark transition-colors flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50"
                      >
                        <RefreshCw className={`w-4 h-4 ${(reprocessing || bulkProcessing) ? 'animate-spin' : ''}`} />
                        {reprocessing ? 'Reprocessing...' : 'Trigger Bulk Reprocess'}
                      </button>

                      <div className="p-3 bg-surface-container-low rounded border border-surface-container-high text-technical-sm text-text-secondary leading-relaxed">
                        OCR-cached reprocessing runs in seconds without Ollama's OCR overhead, ideal for updating summaries or project labels.
                      </div>
                    </div>
                  </div>
                )}

                  <div className="p-5 rounded-lg border border-surface-container-high bg-white text-neutral-dark">
                    <h3 className="font-semibold text-headline-sm mb-2 flex items-center gap-2">
                      <Shield className="w-5 h-5 text-primary-container" /> 100% Local Privacy
                    </h3>
                    <p className="text-text-secondary text-body-sm leading-relaxed">
                      All calculations are performed completely on-device. Images are never uploaded to remote servers. All analysis models run locally via Ollama, guaranteeing absolute data sovereignty.
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* TAB 2: SCREENSHOT LIBRARY & SEARCH */}
            {activeTab === 'gallery' && (
              <div className="space-y-6">
                
                {/* Search Header (Flat corporate search card) */}
                <div className="bg-surface-container-lowest border border-surface-container-high p-4 rounded-lg">
                  <form onSubmit={(e) => { e.preventDefault(); fetchHistory(1) }} className="flex flex-col sm:flex-row items-center gap-3">
                    <div className="relative flex-1 w-full">
                      <Search className="w-4 h-4 text-text-secondary absolute left-4 top-1/2 -translate-y-1/2" />
                      <input
                        type="text"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        placeholder="Search semantic features (e.g., 'coding in python' or 'purple dashboard text')..."
                        className="w-full pl-11 pr-5 h-10 text-body-md rounded bg-white border border-surface-container-high text-on-surface focus:outline-none focus:border-primary-container"
                      />
                    </div>
                    <div className="flex flex-wrap gap-2 w-full sm:w-auto">
                      <button
                        type="submit"
                        disabled={loadingHistory}
                        className="flex-1 sm:flex-initial bg-primary-container hover:bg-primary text-white text-action-md font-medium h-10 px-6 rounded flex items-center justify-center gap-2 transition-colors disabled:opacity-50 select-none cursor-pointer"
                      >
                        <RefreshCw className={`w-4 h-4 ${loadingHistory ? 'animate-spin' : ''}`} />
                        Search
                      </button>
                      <button
                        type="button"
                        onClick={clearSearch}
                        className="bg-surface-container-low hover:bg-surface-container text-neutral-dark text-action-md font-medium h-10 px-4 rounded border border-surface-container-high transition-colors select-none cursor-pointer"
                      >
                        Clear
                      </button>
                      {(status?.pending_queue_size ?? 0) > 0 && (
                        <button
                          type="button"
                          onClick={handleProcessAll}
                          disabled={bulkProcessing}
                          className="bg-accent-surface hover:bg-surface-container text-primary text-action-md font-medium h-10 px-4 rounded border border-primary/20 transition-colors select-none flex items-center gap-1.5 cursor-pointer"
                        >
                          <Cpu className={`w-4 h-4 ${bulkProcessing ? 'animate-spin' : ''}`} />
                          Process All ({status?.pending_queue_size ?? 0})
                        </button>
                      )}
                    </div>
                  </form>
                </div>

                {/* Screenshots Gallery Grid */}
                {loadingHistory ? (
                  <div className="text-center py-20">
                    <div className="w-12 h-12 border-4 border-primary-container border-t-transparent rounded-full animate-spin mx-auto"></div>
                    <p className="text-text-secondary text-body-sm mt-4">Consulting local LanceDB vector search...</p>
                  </div>
                ) : historyRecords.length === 0 ? (
                  <div className="text-center py-16 bg-surface-container-lowest rounded-lg border border-surface-container-high max-w-2xl mx-auto space-y-3">
                    <ImageIcon className="w-12 h-12 text-outline-variant mx-auto" />
                    <h3 className="font-semibold text-headline-sm text-neutral-dark">No screen captures found</h3>
                    <p className="text-text-secondary text-body-sm max-w-md mx-auto px-4 leading-relaxed">
                      Capture logs are created every minute while active. Make sure the watcher is active and the bulk processor has parsed files.
                    </p>
                  </div>
                ) : (
                  <>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    {historyRecords.map((rec) => (
                      <div
                        key={rec.id || Math.random().toString()}
                        className="flex flex-col bg-surface-container-lowest rounded-lg overflow-hidden border border-surface-container-high transition-all"
                      >
                        {/* Image Frame Wrapper (Strictly Flat Design) */}
                        <div 
                          className="relative h-48 bg-surface-container flex items-center justify-center overflow-hidden cursor-pointer border-b border-surface-container-high"
                          onClick={() => openImageLightbox(rec)}
                        >
                          {rec.image_filename ? (
                            <>
                              {/* View mode toggle at bottom-left */}
                              <div 
                                className="absolute bottom-2 left-2 z-10 flex gap-1 bg-white/95 p-0.5 rounded border border-surface-container-high text-[9px] font-semibold font-messina"
                                onClick={(e) => e.stopPropagation()}
                              >
                                <button
                                  type="button"
                                  onClick={() => setCardViewFull(prev => ({...prev, [rec.id]: false}))}
                                  className={`px-1.5 py-0.5 rounded-sm transition-colors cursor-pointer ${!cardViewFull[rec.id] ? 'bg-primary text-white font-bold' : 'text-text-secondary hover:text-neutral-dark'}`}
                                >
                                  Active
                                </button>
                                <button
                                  type="button"
                                  onClick={() => setCardViewFull(prev => ({...prev, [rec.id]: true}))}
                                  className={`px-1.5 py-0.5 rounded-sm transition-colors cursor-pointer ${cardViewFull[rec.id] ? 'bg-primary text-white font-bold' : 'text-text-secondary hover:text-neutral-dark'}`}
                                >
                                  Full
                                </button>
                              </div>

                              <img
                                src={`${API_BASE}/api/screenshots/${cardViewFull[rec.id] ? rec.image_filename.replace('.png', '_full.png') : rec.image_filename}`}
                                className="w-full h-full object-cover"
                                alt="Computer desktop capture"
                                loading="lazy"
                              />
                              <div className="absolute inset-0 bg-neutral-dark/10 opacity-0 hover:opacity-100 flex items-center justify-center transition-opacity">
                                <div className="w-10 h-10 bg-white border border-surface-container-high rounded-full flex items-center justify-center">
                                  <Maximize2 className="w-4 h-4 text-primary" />
                                </div>
                              </div>
                            </>
                          ) : (
                            <div className="absolute inset-0 bg-surface-container-low flex flex-col items-center justify-center p-4 text-center">
                              <Archive className="w-10 h-10 text-disabled mb-2 opacity-50" />
                              <span className="text-[10px] font-semibold text-text-secondary uppercase tracking-wider font-messina">Archived Metadata</span>
                              <span className="text-[10px] text-text-secondary mt-1">Screenshot purged (14-day storage threshold)</span>
                            </div>
                          )}

                          {/* Float Metadata Badges (Flat labels) */}
                          <span className="absolute bottom-2 right-2 bg-neutral-dark text-white text-[10px] font-mono px-2 py-0.5 rounded">
                            {formatTimestamp(rec.timestamp)}
                          </span>

                          {rec.is_processed && (
                            <div className="absolute top-2 left-2 z-10 flex items-center gap-1.5 bg-white/95 border border-surface-container-high px-2 py-1 rounded select-none font-messina" onClick={(e) => e.stopPropagation()}>
                              {rec.human_labeled && (
                                <div className="flex items-center gap-0.5 text-primary font-bold text-[9px] uppercase tracking-wider pr-1.5 border-r border-surface-container-high" title="Manually Verified Project Label">
                                  <User className="w-3 h-3 text-primary-container" />
                                  <span>Verified</span>
                                </div>
                              )}
                              <select
                                value={rec.project_number || 'None'}
                                onChange={(e) => {
                                  const val = e.target.value;
                                  handleUpdateLabel(rec.id, val === 'None' ? null : val);
                                }}
                                className="bg-transparent text-[10px] font-semibold text-neutral-dark outline-none cursor-pointer border-0 p-0 pr-1 select-none"
                              >
                                <option value="None">Unclassified</option>
                                {projectsList.filter(p => p.project_number !== 'Unclassified').map(proj => (
                                  <option key={proj.project_number} value={proj.project_number}>
                                    {proj.project_number}
                                  </option>
                                ))}
                              </select>
                              
                              <button
                                type="button"
                                onClick={() => handleReprocessSnapshots({ ids: [rec.id], reprocessOcr: false })}
                                disabled={processingIds.includes(rec.id)}
                                className="pl-1.5 border-l border-surface-container-high text-text-secondary hover:text-primary transition-colors cursor-pointer"
                                title="Reprocess snapshot (OCR-cached)"
                              >
                                <RefreshCw className={`w-3 h-3 ${processingIds.includes(rec.id) ? 'animate-spin text-primary' : ''}`} />
                              </button>
                            </div>
                          )}

                          {rec.distance !== undefined && (
                            <span className="absolute top-2 right-2 bg-secondary text-white text-[9px] font-semibold px-1.5 py-0.5 rounded">
                              Match: {Math.max(0, Math.round((1 - rec.distance) * 100))}%
                            </span>
                          )}
                        </div>

                        {/* Card Body details */}
                        <div className="p-4 flex-1 flex flex-col justify-between space-y-4">
                          <div>
                            <div className="flex items-center gap-2 mb-2">
                              <span className="px-2 h-6 flex items-center bg-surface-container-low border border-surface-container-high rounded text-technical-sm text-text-secondary max-w-[150px] truncate">
                                {rec.app_name}
                              </span>
                              {rec.is_afk && (
                                <span className="px-2 h-6 flex items-center bg-danger-surface text-danger-primary rounded-full text-indicator-bold border border-danger-primary/20">
                                  AFK
                                </span>
                              )}
                              {!rec.is_processed && (
                                <span className="px-2 h-6 flex items-center bg-warning-light text-neutral-dark rounded-full text-indicator-bold border border-attention-yellow/30 animate-pulse-slow">
                                  Pending
                                </span>
                              )}
                            </div>

                            <h4 className="font-semibold text-headline-sm text-neutral-dark truncate" title={rec.window_title}>
                              {rec.window_title}
                            </h4>

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

                            {/* OCR snippet if present (Technical monospace font) */}
                            {rec.is_processed && rec.ocr_text && (
                              <div className="mt-3 bg-surface-container-low p-2.5 rounded border border-surface-container-high">
                                <button
                                  onClick={() => setExpandedOcrCardId(expandedOcrCardId === rec.id ? null : rec.id)}
                                  className="w-full text-left flex items-center justify-between text-[10px] font-semibold uppercase tracking-wider text-text-secondary font-messina"
                                >
                                  <span className="flex items-center gap-1.5"><FileText className="w-3.5 h-3.5 text-primary-container" /> Extracted OCR Text</span>
                                  <span className="text-primary-container">{expandedOcrCardId === rec.id ? 'Collapse' : 'Expand'}</span>
                                </button>
                                <div className={`transition-all duration-200 overflow-hidden ${expandedOcrCardId === rec.id ? 'max-h-48 mt-2 overflow-y-auto' : 'max-h-5 overflow-hidden'}`}>
                                  <pre className="text-technical-sm font-mono text-neutral-dark whitespace-pre-wrap leading-normal block pt-1 select-all">
                                    {rec.ocr_text}
                                  </pre>
                                </div>
                              </div>
                            )}
                          </div>

                          {/* Tag Badges / Force Process Option */}
                          {rec.is_processed ? (
                            <div className="space-y-2 pt-2 border-t border-surface-container">
                              {rec.tags && rec.tags.length > 0 && (
                                <div className="flex flex-wrap gap-1">
                                  {rec.tags.map((tag) => (
                                    <span key={tag} className="text-[10px] font-semibold bg-accent-surface text-primary px-1.5 py-0.5 rounded">
                                      #{tag}
                                    </span>
                                  ))}
                                </div>
                              )}

                              {/* Logs Terminal snippet during reprocessing */}
                              {(processingIds.includes(rec.id) || (logs[rec.id] && logs[rec.id].length > 0)) && (
                                <div className="bg-surface-container-low border border-surface-container-high text-text-secondary font-mono text-[10px] p-2 rounded max-h-[120px] overflow-y-auto space-y-0.5 mt-1 select-all">
                                  <div className="text-[9px] font-semibold text-text-primary uppercase tracking-wider mb-1 flex items-center justify-between border-b border-surface-container pb-1 font-messina">
                                    <span>Reprocessing Terminal</span>
                                    {processingIds.includes(rec.id) && (
                                      <span className="w-1.5 h-1.5 rounded-full bg-success-green animate-ping"></span>
                                    )}
                                  </div>
                                  {logs[rec.id]?.map((line, idx) => (
                                    <div key={idx} className="leading-normal break-all text-left">{line}</div>
                                  ))}
                                </div>
                              )}
                            </div>
                          ) : (
                            <div className="pt-2 border-t border-surface-container">
                              <button
                                type="button"
                                onClick={() => handleForceProcess(rec.id)}
                                disabled={processingIds.includes(rec.id)}
                                className="w-full bg-primary-container hover:bg-primary text-white text-action-md font-semibold py-2 px-3 rounded flex items-center justify-center gap-2 transition-colors disabled:opacity-50 select-none cursor-pointer"
                              >
                                {processingIds.includes(rec.id) ? (
                                  <RefreshCw className="w-4 h-4 animate-spin" />
                                ) : (
                                  <Cpu className="w-4 h-4" />
                                )}
                                {processingIds.includes(rec.id) ? 'Processing...' : 'Process Screenshot'}
                              </button>

                              {/* Logs Terminal snippet */}
                              {logs[rec.id] && logs[rec.id].length > 0 && (
                                <div className="bg-surface-container-low border border-surface-container-high text-text-secondary font-mono text-[10px] p-2 rounded max-h-[120px] overflow-y-auto space-y-0.5 mt-2 select-all">
                                  <div className="text-[9px] font-semibold text-text-primary uppercase tracking-wider mb-1 flex items-center justify-between border-b border-surface-container pb-1 font-messina">
                                    <span>Processing Terminal</span>
                                    {processingIds.includes(rec.id) && (
                                      <span className="w-1.5 h-1.5 rounded-full bg-success-green animate-ping"></span>
                                    )}
                                  </div>
                                  {logs[rec.id].map((line, idx) => (
                                    <div key={idx} className="leading-normal break-all text-left">{line}</div>
                                  ))}
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
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
                              ? 'bg-primary-container border-primary-container text-white font-semibold'
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
                </>)}
              </div>
            )}

            {/* TAB 3: PROJECT MAPPING DASHBOARD */}
            {activeTab === 'projects' && (
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                
                {/* Tracked Project Listing */}
                <div className="lg:col-span-2 bg-surface-container-lowest border border-surface-container-high p-6 rounded-lg h-fit space-y-4">
                  <div>
                    <h3 className="font-semibold text-headline-sm text-neutral-dark">Tracked Hours by Project Guidelines</h3>
                    <p className="text-text-secondary text-body-sm mt-1">
                      Durations are compiled automatically by scanning screenshots, window focus records, and evaluating match criteria.
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
                              <span className="bg-primary-container text-white text-technical-sm font-semibold px-3 py-1 rounded">
                                {proj.project_number}
                              </span>
                              <strong className="text-neutral-dark text-headline-sm">{proj.description}</strong>
                            </div>
                            {/* Noto Sans reserved exclusively for Quantitative tracking values */}
                            <span className="text-display-progress text-primary-container font-noto tracking-tight">
                              {proj.tracked_hours || 0} h
                            </span>
                          </div>

                          <p className="text-text-secondary text-body-sm leading-relaxed">{proj.work_entailment}</p>

                          <div className="space-y-1">
                            <div className="w-full h-2 bg-surface-container rounded-full overflow-hidden">
                              <div
                                className="h-full bg-primary-container rounded-full transition-all duration-500"
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
                    <h3 className="font-semibold text-headline-sm text-neutral-dark">Configure Project Guidelines</h3>
                    <p className="text-text-secondary text-body-sm mt-1 leading-relaxed">
                      Define project guidelines as JSON. This criteria dictates how the LLM vision system automatically categorizes and segments newly indexed screenshots.
                    </p>
                  </div>

                  <textarea
                    value={projectsJsonInput}
                    onChange={(e) => setProjectsJsonInput(e.target.value)}
                    rows={12}
                    className="w-full p-3 font-mono text-technical-sm text-neutral-dark bg-surface-container-low border border-surface-container-high rounded focus:outline-none focus:border-primary-container"
                  ></textarea>

                  <button
                    onClick={saveProjectsJson}
                    disabled={savingProjects}
                    className="w-full bg-primary-container hover:bg-primary text-white font-messina text-action-lg font-medium h-10 px-4 rounded flex items-center justify-center gap-2 transition-colors disabled:opacity-50 select-none"
                  >
                    <Save className="w-4 h-4" />
                    {savingProjects ? 'Saving...' : 'Save Configurations'}
                  </button>
                </div>
              </div>
            )}
          </>
        )}

        {/* Lightbox Screenshot Overlay Modal */}
        {lightboxOpen && selectedRecord && (
          <div className="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center p-4">
            <div className="fixed inset-0 bg-neutral-dark/80" onClick={() => setLightboxOpen(false)}></div>
            
            <div className="relative z-10 max-w-4xl w-full bg-surface-container-lowest rounded-lg overflow-hidden border border-surface-container-high flex flex-col">
              
              {/* Close Button */}
              <button
                onClick={() => setLightboxOpen(false)}
                className="absolute top-4 right-4 z-20 w-8 h-8 rounded border border-surface-container-high bg-white/90 hover:bg-surface-container-low text-text-secondary hover:text-neutral-dark flex items-center justify-center transition-colors"
              >
                <X className="w-4 h-4" />
              </button>

              {/* Image Frame */}
              <div className="bg-surface-container flex justify-center items-center p-3 border-b border-surface-container-high h-[380px] md:h-[450px] relative">
                {selectedRecord.image_filename && (
                  <div className="absolute top-4 left-4 z-20 flex gap-1 bg-white/95 p-0.5 rounded border border-surface-container-high text-[10px] font-semibold font-messina select-none">
                    <button
                      type="button"
                      onClick={() => setLightboxViewFull(false)}
                      className={`px-2.5 py-1 rounded-sm transition-colors cursor-pointer ${!lightboxViewFull ? 'bg-primary text-white font-bold' : 'text-text-secondary hover:text-neutral-dark'}`}
                    >
                      Active Window Crop
                    </button>
                    <button
                      type="button"
                      onClick={() => setLightboxViewFull(true)}
                      className={`px-2.5 py-1 rounded-sm transition-colors cursor-pointer ${lightboxViewFull ? 'bg-primary text-white font-bold' : 'text-text-secondary hover:text-neutral-dark'}`}
                    >
                      Full Desktop
                    </button>
                  </div>
                )}

                {selectedRecord.image_filename ? (
                  <img
                    src={`${API_BASE}/api/screenshots/${lightboxViewFull ? selectedRecord.image_filename.replace('.png', '_full.png') : selectedRecord.image_filename}`}
                    className="max-w-full max-h-full rounded object-contain"
                    alt="Desktop Full View"
                  />
                ) : (
                  <div className="text-center p-8 space-y-3">
                    <Archive className="w-16 h-16 text-disabled mx-auto opacity-50" />
                    <h3 className="font-semibold text-headline-sm text-neutral-dark">Screenshot Image Archived</h3>
                    <p className="text-text-secondary text-body-sm max-w-md mx-auto leading-relaxed">
                      This screen capture occurred more than 14 days ago. To preserve disk footprint, the binary image file has been cleanly purged from disk, but its analysis descriptions, tags, and semantic indexing vector are retained permanently.
                    </p>
                  </div>
                )}
              </div>

              {/* Text metadata footer content */}
              <div className="p-5 md:p-6 space-y-4 max-h-[220px] overflow-y-auto bg-white text-neutral-dark">
                <div className="flex flex-wrap items-center justify-between gap-3 text-technical-sm">
                  <div className="flex items-center gap-2">
                    {selectedRecord.is_processed ? (
                      <div className="flex items-center gap-1.5 bg-surface-container-low border border-surface-container-high px-2.5 py-1 rounded font-messina">
                        {selectedRecord.human_labeled && (
                          <div className="flex items-center gap-1 text-primary font-bold text-[10px] uppercase tracking-wider pr-1.5 border-r border-surface-container-high" title="Manually Verified Project Label">
                            <User className="w-3.5 h-3.5 text-primary-container" />
                            <span>Verified</span>
                          </div>
                        )}
                        <select
                          value={selectedRecord.project_number || 'None'}
                          onChange={(e) => {
                            const val = e.target.value;
                            handleUpdateLabel(selectedRecord.id, val === 'None' ? null : val);
                          }}
                          className="bg-transparent text-[11px] font-semibold text-neutral-dark outline-none cursor-pointer border-0 p-0 pr-1"
                        >
                          <option value="None">Unclassified</option>
                          {projectsList.filter(p => p.project_number !== 'Unclassified').map(proj => (
                            <option key={proj.project_number} value={proj.project_number}>
                              {proj.project_number}
                            </option>
                          ))}
                        </select>
                      </div>
                    ) : (
                      <span className="bg-surface-container-low text-text-secondary font-semibold px-2.5 py-1 rounded border border-surface-container-high">
                        Pending classification
                      </span>
                    )}
                    <span className="bg-surface-container-low text-text-secondary font-semibold px-2.5 py-1 rounded border border-surface-container-high">
                      {selectedRecord.app_name}
                    </span>
                  </div>
                  <span className="text-text-secondary font-medium font-mono">{formatTimestamp(selectedRecord.timestamp)}</span>
                </div>

                <div className="space-y-1">
                  <h4 className="font-semibold text-headline-sm leading-tight">{selectedRecord.window_title}</h4>
                  <p className="text-text-secondary text-body-sm leading-relaxed">{selectedRecord.description}</p>
                </div>

                {/* Unique Scene Elements & Tools */}
                {selectedRecord.is_processed && selectedRecord.unique_things && (
                  <div className="bg-surface-container-low p-4 rounded border border-surface-container-high space-y-2">
                    <h5 className="text-[10px] font-semibold uppercase tracking-wider text-text-secondary flex items-center gap-1.5 font-messina">
                      <Sparkles className="w-4 h-4 text-primary-container" /> Unique Scene Elements &amp; Tools
                    </h5>
                    <div className="bg-white border border-surface-container p-3 rounded space-y-1.5 max-h-48 overflow-y-auto text-left">
                      {selectedRecord.unique_things.split('\n')
                        .map(line => line.replace(/^[-\*\s•\d\.]+\s*/, '').trim())
                        .filter(line => line.length > 0)
                        .map((thing, idx) => (
                          <div key={idx} className="flex items-start gap-2 text-body-sm text-neutral-dark font-medium">
                            <span className="w-1.5 h-1.5 bg-primary-container rounded-full mt-1.5 flex-shrink-0"></span>
                            <span>{thing}</span>
                          </div>
                        ))}
                    </div>
                  </div>
                )}

                {/* Lightbox full OCR text preview (IBM Plex Mono) */}
                {selectedRecord.ocr_text && (
                  <div className="bg-surface-container-low p-4 rounded border border-surface-container-high space-y-2">
                    <h5 className="text-[10px] font-semibold uppercase tracking-wider text-text-secondary flex items-center gap-1.5 font-messina">
                      <FileText className="w-4 h-4 text-primary-container" /> Fully Parsed Code &amp; Extracted Text (OCR)
                    </h5>
                    <pre className="text-technical-sm font-mono text-neutral-dark whitespace-pre-wrap select-all max-h-48 overflow-y-auto border border-surface-container p-2 rounded bg-white leading-normal">
                      {selectedRecord.ocr_text}
                    </pre>
                  </div>
                )}

                {/* Tag items / Lightbox Force Process option */}
                {selectedRecord.is_processed ? (
                  <div className="space-y-4">
                    {selectedRecord.tags && selectedRecord.tags.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 pt-2 border-t border-surface-container">
                        {selectedRecord.tags.map((tag) => (
                          <span key={tag} className="text-technical-sm font-semibold bg-accent-surface border border-surface-container-high text-primary px-2 py-0.5 rounded">
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
                        disabled={processingIds.includes(selectedRecord.id)}
                        className="w-full bg-neutral-dark hover:bg-neutral text-white text-action-sm font-semibold py-2 px-3 rounded flex items-center justify-center gap-2 transition-colors disabled:opacity-50 select-none cursor-pointer"
                        title="Reprocess this snapshot to refresh tags, project guesses, and descriptions"
                      >
                        <RefreshCw className={`w-4 h-4 ${processingIds.includes(selectedRecord.id) ? 'animate-spin' : ''}`} />
                        {processingIds.includes(selectedRecord.id) ? 'Reprocessing Snapshot...' : 'Reprocess Snapshot (OCR-cached)'}
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
                      disabled={processingIds.includes(selectedRecord.id)}
                      className="w-full bg-primary-container hover:bg-primary text-white text-action-sm font-semibold py-2 px-3 rounded flex items-center justify-center gap-2 transition-colors disabled:opacity-50 select-none cursor-pointer"
                    >
                      {processingIds.includes(selectedRecord.id) ? (
                        <RefreshCw className="w-4 h-4 animate-spin" />
                      ) : (
                        <Cpu className="w-4 h-4" />
                      )}
                      {processingIds.includes(selectedRecord.id) ? 'Processing Screenshot...' : 'Process Screenshot Now'}
                    </button>
                  </div>
                )}

                {/* Persistent/Historic Step logs (Collapsible console snippet) */}
                {logs[selectedRecord.id] && logs[selectedRecord.id].length > 0 && (
                  <div className="bg-surface-container-low p-4 rounded border border-surface-container-high space-y-2 mt-3">
                    <button
                      onClick={() => setExpandedOcrCardId(expandedOcrCardId === `logs-${selectedRecord.id}` ? null : `logs-${selectedRecord.id}`)}
                      className="w-full text-left flex items-center justify-between text-[10px] font-semibold uppercase tracking-wider text-text-secondary font-messina"
                    >
                      <span className="flex items-center gap-1.5">
                        <FileText className="w-3.5 h-3.5 text-primary-container" /> 
                        Processing Step Logs
                      </span>
                      <span className="text-primary-container">
                        {expandedOcrCardId === `logs-${selectedRecord.id}` ? 'Hide Logs' : 'View Logs'}
                      </span>
                    </button>
                    <div className={`transition-all duration-200 overflow-hidden ${expandedOcrCardId === `logs-${selectedRecord.id}` ? 'max-h-48 overflow-y-auto' : 'max-h-0'}`}>
                      <div className="bg-surface-container-low border border-surface-container text-text-secondary font-mono text-[10px] p-3 rounded space-y-0.5 select-all leading-normal">
                        {logs[selectedRecord.id].map((line, idx) => (
                          <div key={idx} className="leading-normal break-all text-left">{line}</div>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Floating Google Photos-Style Timeline Scrollbar */}
        {activeTab === 'gallery' && timelineEntries.length > 1 && (
          <div className="fixed right-6 top-1/2 -translate-y-1/2 z-40 hidden xl:flex flex-col items-end gap-4 p-4 bg-surface-container-lowest border border-surface-container-high rounded max-h-[80vh] overflow-y-auto shadow-none">
            <div className="text-[10px] font-semibold font-messina text-text-secondary uppercase tracking-wider mb-2 border-b border-surface-container-high pb-1 w-full text-right">
              Timeline
            </div>
            <div className="relative flex flex-col gap-6 pr-1.5 py-2 border-r-2 border-surface-container-high">
              {timelineEntries.map((entry) => {
                const isActive = currentPage === entry.page
                return (
                  <div
                    key={entry.label}
                    onClick={() => fetchHistory(entry.page)}
                    className="flex items-center gap-3 group cursor-pointer justify-end mr-[-8px]"
                    title={`${entry.label} (${entry.count} captures)`}
                  >
                    <span className={`text-[10px] font-semibold font-messina uppercase tracking-wider transition-colors text-right select-none ${
                      isActive 
                        ? 'text-primary-container font-bold' 
                        : 'text-text-secondary group-hover:text-neutral-dark'
                    }`}>
                      {entry.label}
                    </span>
                    <div className={`w-3.5 h-3.5 rounded-full border transition-all ${
                      isActive
                        ? 'bg-primary-container border-primary-container scale-110'
                        : 'bg-white border-outline-variant group-hover:border-primary-container'
                    }`} />
                  </div>
                )
              })}
            </div>
          </div>
        )}

      </div>
    </div>
  )
}
