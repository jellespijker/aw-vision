import React, { useState, useEffect, useRef } from 'react'
import axios from 'axios'
import { EyeOff, RefreshCw } from 'lucide-react'

import type { DaemonStatus, HistoryRecord, Project, ChatMessage, TimelineEntry } from './types'
import { NotificationToast } from './components/NotificationToast'
import { Header } from './components/Header'
import { Tabs } from './components/Tabs'
import { AgentTab } from './components/AgentTab'
import { GalleryTab } from './components/GalleryTab'
import { ProjectsTab } from './components/ProjectsTab'
import { PipelineTab } from './components/PipelineTab'
import { SettingsTab } from './components/SettingsTab'
import { LightboxModal } from './components/LightboxModal'

const getApiBase = (): string => {
  if (import.meta.env.VITE_API_BASE_URL) {
    return import.meta.env.VITE_API_BASE_URL
  }
  if (window.location.port !== '5666') {
    return 'http://127.0.0.1:5666'
  }
  return ''
}

export const API_BASE = getApiBase()
axios.defaults.baseURL = API_BASE

export default function App() {
  // Theme and Tab States
  const [darkMode, setDarkMode] = useState<boolean>(false)
  const [activeTab, setActiveTab] = useState<'chat' | 'gallery' | 'projects' | 'pipeline' | 'settings'>('chat')


  // API and Connection States
  const [serverOnline, setServerOnline] = useState<boolean>(true)
  const [status, setStatus] = useState<DaemonStatus | null>(null)
  const [loadingStatus, setLoadingStatus] = useState<boolean>(false)

  // Chat/Agent States
  const [agentPrompt, setAgentPrompt] = useState<string>('')
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [querying, setQuerying] = useState<boolean>(false)

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
    const interval = status?.is_processing ? 1500 : 5000
    const timer = setInterval(getDaemonStatus, interval)
    return () => clearInterval(timer)
  }, [serverOnline, status?.is_processing])

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
      setProcessingIds((prev) => {
        const backendIds = status.processing_ids || []
        const finishedIds = prev.filter((id) => !backendIds.includes(id))

        finishedIds.forEach((id) => {
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

  const prevPendingSize = useRef<number | null>(null)
  const prevProcessedSize = useRef<number | null>(null)

  const fetchNewHistory = async () => {
    if (!serverOnline) return
    try {
      const q = searchQuery
      let url = `/api/history?page=1&limit=${pageSize}`
      if (q && q.trim()) {
        url += `&search=${encodeURIComponent(q.trim())}`
      }
      const resp = await axios.get(url)
      const latestItems = resp.data.items || []

      setHistoryRecords((prev) => {
        const existingIds = new Set(prev.map((item) => item.id))
        const newItems = latestItems.filter((item: HistoryRecord) => !existingIds.has(item.id))
        if (newItems.length === 0) return prev
        return [...newItems, ...prev]
      })

      setTotalCount(resp.data.total || 0)
      setTotalPages(resp.data.total_pages || 1)
    } catch (e) {
      console.error('Error fetching new history', e)
    }
  }

  useEffect(() => {
    if (status) {
      const pendingChanged = prevPendingSize.current !== null && status.pending_queue_size !== prevPendingSize.current
      const processedChanged = prevProcessedSize.current !== null && status.processed_database_size !== prevProcessedSize.current

      if (pendingChanged || processedChanged) {
        fetchNewHistory()
      }

      prevPendingSize.current = status.pending_queue_size
      prevProcessedSize.current = status.processed_database_size
    }
  }, [status])

  // Automatically update the active Lightbox record when the gallery history refreshes
  useEffect(() => {
    if (selectedRecord && historyRecords.length > 0) {
      const match = historyRecords.find((r) => r.id === selectedRecord.id)
      if (match && JSON.stringify(match) !== JSON.stringify(selectedRecord)) {
        setSelectedRecord(match)
      }
    }
  }, [historyRecords, selectedRecord])

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
      const resp = await axios.get('/api/status', { timeout: 5000 })
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
      const resp = await axios.get('/api/status', { timeout: 5000 })
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

  const loadMoreHistory = async () => {
    if (!serverOnline || loadingHistory || currentPage >= totalPages) return
    setLoadingHistory(true)
    try {
      const nextPage = currentPage + 1
      const q = searchQuery
      let url = `/api/history?page=${nextPage}&limit=${pageSize}`
      if (q && q.trim()) {
        url += `&search=${encodeURIComponent(q.trim())}`
      }
      const resp = await axios.get(url)
      const newItems = resp.data.items || []

      setHistoryRecords((prev) => {
        const existingIds = new Set(prev.map((item) => item.id))
        const filteredNew = newItems.filter((item: HistoryRecord) => !existingIds.has(item.id))
        return [...prev, ...filteredNew]
      })

      setCurrentPage(resp.data.page || nextPage)
      setTotalPages(resp.data.total_pages || 1)
    } catch (e) {
      console.error('Error loading more history', e)
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
    setProcessingIds((prev) => [...prev, fileId])

    const pollLogs = async () => {
      try {
        const resp = await axios.get(`/api/process/${fileId}/logs`)
        if (resp.data && resp.data.logs) {
          setLogs((prev) => ({ ...prev, [fileId]: resp.data.logs }))
        }
      } catch (err) {
        console.error('Error polling logs:', err)
      }
    }

    pollLogs()
    const interval = setInterval(pollLogs, 1000)
    pollingIntervals.current[fileId] = interval

    try {
      const resp = await axios.post(`/api/process/${fileId}`)
      if (resp.status === 200) {
        setToastMessage({ text: 'Screenshot processed successfully!', type: 'success' })
        fetchHistory(currentPage)
        getDaemonStatus()

        if (selectedRecord && selectedRecord.id === fileId) {
          setSelectedRecord(resp.data as HistoryRecord)
        }

        return resp.data as HistoryRecord
      }
    } catch (e: any) {
      const errMsg = e.response?.data?.detail || e.message || 'Error occurred'
      setToastMessage({ text: `Failed to process screenshot: ${errMsg}`, type: 'danger' })
    } finally {
      setProcessingIds((prev) => prev.filter((id) => id !== fileId))
      if (pollingIntervals.current[fileId]) {
        clearInterval(pollingIntervals.current[fileId])
        delete pollingIntervals.current[fileId]
      }
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
      setProcessingIds((prev) => Array.from(new Set([...prev, targetId])))
    } else {
      setReprocessing(true)
    }

    const pollLogs = async () => {
      if (!targetId) return
      try {
        const resp = await axios.get(`/api/process/${targetId}/logs`)
        if (resp.data && resp.data.logs) {
          setLogs((prev) => ({ ...prev, [targetId]: resp.data.logs }))
        }
      } catch (err) {
        console.error('Error polling logs:', err)
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
        setTimeout(() => {
          if (pollingIntervals.current[targetId]) {
            clearInterval(pollingIntervals.current[targetId])
            delete pollingIntervals.current[targetId]
          }
          setProcessingIds((prev) => prev.filter((id) => id !== targetId))
          fetchHistory(currentPage)
        }, 45000)
      }
    }
    return false
  }

  const handleBulkReprocessSidebar = async () => {
    const options: any = { reprocessOcr }

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

        setHistoryRecords((prev) =>
          prev.map((rec) => {
            if (rec.id === recordId) {
              return {
                ...rec,
                project_number: projectNumber,
                human_labeled: true
              }
            }
            return rec
          })
        )

        setSelectedRecord((prev) => {
          if (prev && prev.id === recordId) {
            return {
              ...prev,
              project_number: projectNumber,
              human_labeled: true
            }
          }
          return prev
        })

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

    try {
      const resp = await axios.get(`/api/process/${rec.id}/logs`)
      if (resp.data && resp.data.logs) {
        setLogs((prev) => ({ ...prev, [rec.id]: resp.data.logs }))
      }
    } catch (err) {
      console.error('Error loading processing logs for record:', err)
    }
  }

  const formatTimestamp = (ts: number) => {
    if (!ts) return ''
    const d = new Date(ts * 1000)
    return (
      d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) +
      ' ' +
      d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
    )
  }

  const getPageRange = () => {
    let startPage = Math.max(1, currentPage - 2)
    const endPage = Math.min(totalPages, startPage + 4)
    if (endPage - startPage < 4) {
      startPage = Math.max(1, endPage - 4)
    }
    const range = []
    for (let i = startPage; i <= endPage; i++) {
      range.push(i)
    }
    return range
  }

  return (
    <div
      className={`min-h-screen ${
        darkMode ? 'dark bg-surface text-on-surface' : 'bg-surface text-on-surface'
      }`}
    >
      <div className="max-w-7xl mx-auto px-6 py-6 lg:px-8">
        {/* Toast Alerts Notification bar */}
        <NotificationToast message={toastMessage} onClose={() => setToastMessage(null)} />

        {/* Server Offline Warning Card */}
        {!serverOnline && (
          <div className="bg-danger-surface border-danger-primary dark:bg-danger-primary/10 dark:border-danger-primary/30 p-5 rounded border mb-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
            <div className="space-y-1">
              <h3 className="text-danger-primary font-semibold text-headline-sm flex items-center gap-2">
                <EyeOff className="w-5 h-5" /> aw-vision Backend is Offline
              </h3>
              <p className="text-neutral-dark text-body-sm">
                To start the local screen capture ingestion loops and semantic recollecting API, execute the following command in your terminal inside the <code className="text-danger-primary bg-surface-container-lowest px-1.5 py-0.5 rounded text-technical-sm border border-danger-primary/30">aw-vision</code> workspace:
              </p>
              <pre className="bg-surface-container-lowest text-danger-primary p-2.5 rounded border border-danger-primary/25 text-technical-sm font-mono select-all inline-block mt-2">
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
        <Header
          darkMode={darkMode}
          setDarkMode={setDarkMode}
          serverOnline={serverOnline}
          status={status}
          checkServerStatus={checkServerStatus}
        />

        {serverOnline && (
          <>
            {/* Tabs Navigation */}
            <Tabs activeTab={activeTab} setActiveTab={setActiveTab} totalCount={totalCount} />

            <main id="main-content" className="flex-grow">
              {/* TAB 1: ASK MEMORY AGENT */}
              {activeTab === 'chat' && (
                <AgentTab
                  chatMessages={chatMessages}
                  querying={querying}
                  agentPrompt={agentPrompt}
                  setAgentPrompt={setAgentPrompt}
                  submitAgentQuery={submitAgentQuery}
                  historyRecords={historyRecords}
                  projectsList={projectsList}
                  openImageLightbox={openImageLightbox}
                  API_BASE={API_BASE}
                  status={status}
                />
              )}

                            {/* TAB 2: SCREENSHOT LIBRARY & SEARCH */}
              {activeTab === 'gallery' && (
                <GalleryTab
                  status={status}
                  searchQuery={searchQuery}
                  setSearchQuery={setSearchQuery}
                  loadingHistory={loadingHistory}
                  fetchHistory={fetchHistory}
                  clearSearch={clearSearch}
                  handleProcessAll={handleProcessAll}
                  bulkProcessing={bulkProcessing}
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
                  currentPage={currentPage}
                  totalPages={totalPages}
                  getPageRange={getPageRange}
                  expandedOcrCardId={expandedOcrCardId}
                  setExpandedOcrCardId={setExpandedOcrCardId}
                  hasMore={currentPage < totalPages}
                  loadMore={loadMoreHistory}
                  totalCount={totalCount}
                />
              )}

              {/* TAB 3: PROJECT MAPPING DASHBOARD */}
              {activeTab === 'projects' && (
                <ProjectsTab
                  projectsList={projectsList}
                  projectsJsonInput={projectsJsonInput}
                  setProjectsJsonInput={setProjectsJsonInput}
                  saveProjectsJson={saveProjectsJson}
                  savingProjects={savingProjects}
                />
              )}

              {/* TAB 4: SYSTEM PIPELINE */}
              {activeTab === 'pipeline' && (
                <PipelineTab
                  status={status}
                  bulkProcessing={bulkProcessing}
                  handleProcessAll={handleProcessAll}
                  reprocessRange={reprocessRange}
                  setReprocessRange={setReprocessRange}
                  reprocessOcr={reprocessOcr}
                  setReprocessOcr={setReprocessOcr}
                  reprocessing={reprocessing}
                  handleBulkReprocessSidebar={handleBulkReprocessSidebar}
                />
              )}

              {/* TAB 5: AI & SYSTEM SETTINGS */}
              {activeTab === 'settings' && (
                <SettingsTab
                  showNotification={(text, type) => {
                    setToastMessage({ text, type })
                  }}
                />
              )}
            </main>
          </>
        )}


        {/* Lightbox Screenshot Overlay Modal */}
        <LightboxModal
          isOpen={lightboxOpen}
          onClose={() => setLightboxOpen(false)}
          selectedRecord={selectedRecord}
          setSelectedRecord={setSelectedRecord}
          lightboxViewFull={lightboxViewFull}
          setLightboxViewFull={setLightboxViewFull}
          projectsList={projectsList}
          handleUpdateLabel={handleUpdateLabel}
          handleForceProcess={handleForceProcess}
          handleReprocessSnapshots={handleReprocessSnapshots}
          processingIds={processingIds}
          logs={logs}
          expandedOcrCardId={expandedOcrCardId}
          setExpandedOcrCardId={setExpandedOcrCardId}
          formatTimestamp={formatTimestamp}
          API_BASE={API_BASE}
        />

        {/* Floating Google Photos-Style Timeline Scrollbar */}
        {activeTab === 'gallery' && timelineEntries.length > 1 && (
          <div className="fixed right-6 top-1/2 -translate-y-1/2 z-40 hidden xl:flex flex-col items-end gap-4 p-4 bg-surface-container-lowest border border-surface-container-high rounded max-h-[80vh] overflow-y-auto shadow-none">
            <div className="text-[10px] font-semibold font-messina text-text-secondary uppercase tracking-wider mb-2 border-b border-surface-container-high pb-1 w-full text-right select-none">
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
                    <span
                      className={`text-[10px] font-semibold font-messina uppercase tracking-wider transition-colors text-right select-none ${
                        isActive
                          ? 'text-primary font-bold'
                          : 'text-text-secondary group-hover:text-neutral-dark'
                      }`}
                    >
                      {entry.label}
                    </span>
                    <div
                      className={`w-3.5 h-3.5 rounded-full border transition-all ${
                        isActive
                          ? 'bg-primary border-primary scale-110'
                          : 'bg-surface-container-lowest border-outline-variant group-hover:border-primary'
                      }`}
                    />
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
