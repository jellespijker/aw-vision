import React, { useState, useEffect, useRef } from 'react'
import axios from 'axios'

// Configure API base dynamically based on hosting port
const getApiBase = (): string => {
  if (import.meta.env.VITE_API_BASE_URL) {
    return import.meta.env.VITE_API_BASE_URL
  }
  // If hosted on a port that is not port 5666 (backend), point to port 5666
  if (window.location.port !== '5666') {
    return 'http://localhost:5666'
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
  ArrowRight
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
  system_load: SystemLoad
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
}

interface Project {
  project_number: string
  description: string
  work_entailment: string
  tracked_hours: number
}

export default function App() {
  // Theme and Tab States (Defaults to Light Corporate-Neutral Theme)
  const [darkMode, setDarkMode] = useState<boolean>(false)
  const [activeTab, setActiveTab] = useState<'chat' | 'gallery' | 'projects'>('chat')
  
  // API and Connection States
  const [serverOnline, setServerOnline] = useState<boolean>(false)
  const [loadingStatus, setLoadingStatus] = useState<boolean>(false)
  const [status, setStatus] = useState<DaemonStatus>({
    watcher_running: false,
    processor_running: false,
    pending_queue_size: 0,
    processed_database_size: 0,
    system_load: { cpu_percent: 0, memory_percent: 0 }
  })

  // Chat/Agent States
  const [agentPrompt, setAgentPrompt] = useState<string>('')
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [querying, setQuerying] = useState<boolean>(false)
  const chatLogsRef = useRef<HTMLDivElement>(null)

  // Gallery/Search States
  const [searchQuery, setSearchQuery] = useState<string>('')
  const [loadingHistory, setLoadingHistory] = useState<boolean>(false)
  const [historyRecords, setHistoryRecords] = useState<HistoryRecord[]>([])
  const [selectedRecord, setSelectedRecord] = useState<HistoryRecord | null>(null)
  const [lightboxOpen, setLightboxOpen] = useState<boolean>(false)
  const [expandedOcrCardId, setExpandedOcrCardId] = useState<string | null>(null)

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
        fetchHistory()
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

  const fetchHistory = async (queryOverride?: string) => {
    if (!serverOnline) return
    setLoadingHistory(true)
    try {
      const q = queryOverride !== undefined ? queryOverride : searchQuery
      let url = '/api/history?limit=30'
      if (q && q.trim()) {
        url += `&search=${encodeURIComponent(q.trim())}`
      }
      const resp = await axios.get(url)
      setHistoryRecords(resp.data)
    } catch (e) {
      console.error('Error loading screenshot history', e)
    } finally {
      setLoadingHistory(false)
    }
  }

  const clearSearch = () => {
    setSearchQuery('')
    fetchHistory('')
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

  const openImageLightbox = (rec: HistoryRecord) => {
    setSelectedRecord(rec)
    setLightboxOpen(true)
  }

  const formatTimestamp = (ts: number) => {
    if (!ts) return ''
    const d = new Date(ts * 1000)
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
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
                    project_number: null
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

            {serverOnline && (
              <>
                {/* Active Daemon Indicators (Pill shape reserved exclusively for Status Badges) */}
                <div className="bg-surface-container-low border border-surface-container-high px-3 h-10 rounded-full flex items-center gap-2 text-indicator-bold text-neutral-dark">
                  <span className={`w-2.5 h-2.5 rounded-full ${status.watcher_running ? 'bg-success-green' : 'bg-danger-primary'}`}></span>
                  <span>Watcher: {status.watcher_running ? 'ACTIVE' : 'STOPPED'}</span>
                </div>

                <div className="bg-surface-container-low border border-surface-container-high px-3 h-10 rounded-full flex items-center gap-2 text-indicator-bold text-neutral-dark">
                  <span className={`w-2.5 h-2.5 rounded-full ${status.processor_running ? 'bg-success-green animate-pulse-slow' : 'bg-disabled'}`}></span>
                  <span>Processor: {status.processor_running ? 'ACTIVE' : 'IDLE'}</span>
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
                onClick={() => setActiveTab('gallery')}
                className={`h-10 px-5 text-action-md font-medium rounded-t transition-colors border-b-2 flex items-center gap-2 font-messina select-none ${
                  activeTab === 'gallery'
                    ? 'border-primary-container text-primary-container bg-surface-container-lowest'
                    : 'border-transparent text-text-secondary hover:text-neutral-dark hover:bg-surface-container-low'
                }`}
              >
                <ImageIcon className="w-4 h-4" /> Screenshot Library &amp; Search
              </button>
              <button
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
                  <form onSubmit={(e) => { e.preventDefault(); fetchHistory() }} className="flex flex-col sm:flex-row items-center gap-3">
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
                    <div className="flex gap-2 w-full sm:w-auto">
                      <button
                        type="submit"
                        disabled={loadingHistory}
                        className="flex-1 sm:flex-initial bg-primary-container hover:bg-primary text-white text-action-md font-medium h-10 px-6 rounded flex items-center justify-center gap-2 transition-colors disabled:opacity-50 select-none"
                      >
                        <RefreshCw className={`w-4 h-4 ${loadingHistory ? 'animate-spin' : ''}`} />
                        Search
                      </button>
                      <button
                        type="button"
                        onClick={clearSearch}
                        className="bg-surface-container-low hover:bg-surface-container text-neutral-dark text-action-md font-medium h-10 px-4 rounded border border-surface-container-high transition-colors select-none"
                      >
                        Clear
                      </button>
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
                              <img
                                src={`${API_BASE}/api/screenshots/${rec.image_filename}`}
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

                          {rec.project_number && (
                            <span className="absolute top-2 left-2 bg-primary-container text-white text-[10px] font-semibold px-2.5 py-1 rounded">
                              {rec.project_number}
                            </span>
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
                            </div>

                            <h4 className="font-semibold text-headline-sm text-neutral-dark truncate" title={rec.window_title}>
                              {rec.window_title}
                            </h4>

                            <p className="text-text-secondary text-body-sm line-clamp-3 mt-1" title={rec.description}>
                              {rec.description}
                            </p>

                            {/* OCR snippet if present (Technical monospace font) */}
                            {rec.ocr_text && (
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

                          {/* Tag Badges */}
                          {rec.tags.length > 0 && (
                            <div className="flex flex-wrap gap-1 pt-2 border-t border-surface-container">
                              {rec.tags.map((tag) => (
                                <span key={tag} className="text-[10px] font-semibold bg-accent-surface text-primary px-1.5 py-0.5 rounded">
                                  #{tag}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
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
              <div className="bg-surface-container flex justify-center items-center p-3 border-b border-surface-container-high h-[380px] md:h-[450px]">
                {selectedRecord.image_filename ? (
                  <img
                    src={`${API_BASE}/api/screenshots/${selectedRecord.image_filename}`}
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
                    <span className="bg-primary-container text-white font-semibold px-3 py-1 rounded">
                      {selectedRecord.project_number || 'Unclassified'}
                    </span>
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

                {/* Tag items */}
                {selectedRecord.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 pt-2 border-t border-surface-container">
                    {selectedRecord.tags.map((tag) => (
                      <span key={tag} className="text-technical-sm font-semibold bg-accent-surface border border-surface-container-high text-primary px-2 py-0.5 rounded">
                        #{tag}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

      </div>
    </div>
  )
}
