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
  Sparkles,
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
  // Theme and Tab States
  const [darkMode, setDarkMode] = useState<boolean>(true)
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
          <pre key={index} className="bg-slate-900/90 text-slate-100 p-4 rounded-xl my-3 font-mono text-xs overflow-x-auto border border-slate-800/80 shadow-inner">
            {lang && <div className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider mb-2 border-b border-slate-800 pb-1">{lang}</div>}
            <code className="block whitespace-pre select-all">{code}</code>
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
              <strong key={tIdx} className="font-bold text-slate-900 dark:text-white">
                {token.slice(2, -2)}
              </strong>
            )
          }
          if (token.startsWith('`') && token.endsWith('`')) {
            return (
              <code key={tIdx} className="bg-slate-200 dark:bg-slate-800/80 text-rose-600 dark:text-rose-400 px-1.5 py-0.5 rounded font-mono text-xs border border-slate-300 dark:border-slate-700/50">
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
                className="inline-flex flex-col p-1.5 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700/60 rounded-xl mx-1 shadow-sm hover:shadow-lg hover:border-blue-500 hover:-translate-y-0.5 transition-all duration-200 cursor-pointer align-middle max-w-[120px]"
              >
                <img src={`${API_BASE}/api/screenshots/${filename}`} className="w-full h-auto rounded-lg object-cover max-h-[60px]" alt="Thumbnail" />
                <span className="block text-[9px] text-slate-500 dark:text-slate-400 text-center truncate mt-1 font-mono">{filename.substring(0, 8)}...</span>
              </div>
            )
          }
          return token
        })

        return (
          <p key={lIdx} className={`leading-relaxed text-sm ${lIdx === lines.length - 1 ? 'mb-0' : 'mb-2'}`}>
            {lineElements}
          </p>
        )
      })
    })
  }

  return (
    <div className={`min-h-screen transition-colors duration-300 ${darkMode ? 'bg-slate-950 text-slate-100' : 'bg-slate-50 text-slate-800'}`}>
      
      {/* Background abstract glowing orbs for Glassmorphism depth */}
      <div className="absolute top-0 left-0 right-0 h-[500px] overflow-hidden pointer-events-none z-0">
        <div className="absolute -top-40 left-1/4 w-[400px] h-[400px] rounded-full bg-blue-500/10 blur-[120px] dark:bg-blue-600/15"></div>
        <div className="absolute -top-20 right-1/4 w-[450px] h-[450px] rounded-full bg-purple-500/10 blur-[130px] dark:bg-purple-600/15"></div>
      </div>

      <div className="relative z-10 max-w-7xl mx-auto px-4 py-6 sm:px-6 lg:px-8">
        
        {/* Toast Alerts Notification banner */}
        {toastMessage && (
          <div className={`fixed top-5 right-5 z-50 p-4 rounded-xl shadow-2xl flex items-center gap-3 animate-bounce border ${
            toastMessage.type === 'success' 
              ? 'bg-emerald-500/90 border-emerald-400 text-white' 
              : 'bg-rose-500/90 border-rose-400 text-white'
          }`}>
            <Sparkles className="w-5 h-5 shrink-0" />
            <span className="font-semibold text-sm">{toastMessage.text}</span>
          </div>
        )}

        {/* Server Offline Warning Card */}
        {!serverOnline && (
          <div className="glass-card-dark border-rose-500/30 bg-slate-900/80 p-5 rounded-2xl shadow-xl border mb-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-4 animate-pulse-slow">
            <div className="space-y-1">
              <h3 className="text-rose-400 font-bold text-lg flex items-center gap-2">
                <EyeOff className="w-5 h-5" /> aw-vision Backend is Offline
              </h3>
              <p className="text-slate-400 text-sm">
                To start the local screen capture ingestion loops and semantic recollecting API, execute the following command in your terminal inside the <code className="text-rose-300 bg-slate-850 px-1.5 py-0.5 rounded text-xs font-mono font-bold">aw-vision</code> workspace:
              </p>
              <pre className="bg-slate-950 text-emerald-400 p-2.5 rounded-lg border border-slate-800 text-xs font-mono select-all inline-block mt-2">
                poetry run uvicorn aw_vision.server:app --port 5666 --reload
              </pre>
            </div>
            <button
              onClick={checkServerStatus}
              disabled={loadingStatus}
              className="bg-rose-600/85 hover:bg-rose-600 text-white text-sm font-semibold py-2 px-5 rounded-xl border border-rose-500/30 flex items-center gap-2 transition-all shadow shadow-rose-600/25 disabled:opacity-50"
            >
              <RefreshCw className={`w-4 h-4 ${loadingStatus ? 'animate-spin' : ''}`} />
              Retry Connection
            </button>
          </div>
        )}

        {/* Header Section */}
        <header className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8 pb-6 border-b border-slate-200 dark:border-slate-800/80">
          <div>
            <div className="flex items-center gap-2.5 mb-1.5">
              <Layers className="w-7 h-7 text-blue-500 dark:text-blue-400" />
              <h1 className="text-2xl md:text-3.5xl font-extrabold tracking-tight font-display bg-gradient-to-r from-blue-600 to-indigo-500 dark:from-blue-400 dark:to-purple-400 bg-clip-text text-transparent">
                Visual &amp; Semantic Memory
              </h1>
            </div>
            <p className="text-slate-500 dark:text-slate-400 text-sm max-w-2xl">
              Secure, local-first computer history pipeline. Screenshot capture loops, optical text models, and vector embeddings stored completely on-device.
            </p>
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            {/* Theme Toggle Button */}
            <button 
              onClick={() => setDarkMode(!darkMode)}
              className="p-2.5 rounded-xl border border-slate-200 dark:border-slate-800 hover:bg-slate-100 dark:hover:bg-slate-900 text-slate-500 dark:text-slate-400 transition-all shadow-sm"
              title={darkMode ? "Switch to Light Theme" : "Switch to Dark Theme"}
            >
              {darkMode ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4 text-indigo-500" />}
            </button>

            {serverOnline && (
              <>
                {/* Active Daemon Indicators */}
                <div className="glass-card-dark border-slate-200/20 dark:border-slate-800/50 bg-white/50 dark:bg-slate-900/50 px-3 py-1.5 rounded-xl border flex items-center gap-2 text-xs">
                  <span className={`w-2.5 h-2.5 rounded-full ${status.watcher_running ? 'bg-emerald-500 animate-pulse' : 'bg-rose-500'}`}></span>
                  <span className="font-semibold text-slate-500 dark:text-slate-300">Watcher: {status.watcher_running ? 'ACTIVE' : 'STOPPED'}</span>
                </div>

                <div className="glass-card-dark border-slate-200/20 dark:border-slate-800/50 bg-white/50 dark:bg-slate-900/50 px-3 py-1.5 rounded-xl border flex items-center gap-2 text-xs">
                  <span className={`w-2.5 h-2.5 rounded-full ${status.processor_running ? 'bg-emerald-500 animate-pulse' : 'bg-slate-500'}`}></span>
                  <span className="font-semibold text-slate-500 dark:text-slate-300">Processor: {status.processor_running ? 'ACTIVE' : 'IDLE'}</span>
                </div>

                <button
                  onClick={checkServerStatus}
                  className="p-2 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 hover:bg-slate-100 dark:hover:bg-slate-800/80 transition-all text-slate-500 dark:text-slate-400 shadow-sm"
                >
                  <RefreshCw className="w-4 h-4" />
                </button>
              </>
            )}
          </div>
        </header>

        {serverOnline && (
          <>
            {/* Tabs Navigation */}
            <div className="flex border-b border-slate-200 dark:border-slate-800 mb-6 gap-2">
              <button
                onClick={() => setActiveTab('chat')}
                className={`py-3 px-5 text-sm font-semibold rounded-t-xl transition-all border-b-2 flex items-center gap-2 ${
                  activeTab === 'chat'
                    ? 'border-blue-500 text-blue-600 dark:text-blue-400 bg-blue-50/50 dark:bg-blue-950/20'
                    : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-900/50'
                }`}
              >
                <Bot className="w-4 h-4" /> Ask Memory Agent
              </button>
              <button
                onClick={() => setActiveTab('gallery')}
                className={`py-3 px-5 text-sm font-semibold rounded-t-xl transition-all border-b-2 flex items-center gap-2 ${
                  activeTab === 'gallery'
                    ? 'border-blue-500 text-blue-600 dark:text-blue-400 bg-blue-50/50 dark:bg-blue-950/20'
                    : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-900/50'
                }`}
              >
                <ImageIcon className="w-4 h-4" /> Screenshot Library &amp; Search
              </button>
              <button
                onClick={() => setActiveTab('projects')}
                className={`py-3 px-5 text-sm font-semibold rounded-t-xl transition-all border-b-2 flex items-center gap-2 ${
                  activeTab === 'projects'
                    ? 'border-blue-500 text-blue-600 dark:text-blue-400 bg-blue-50/50 dark:bg-blue-950/20'
                    : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-900/50'
                }`}
              >
                <FileText className="w-4 h-4" /> Project Mapping Dashboard
              </button>
            </div>

            {/* TAB 1: ASK MEMORY AGENT */}
            {activeTab === 'chat' && (
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                
                {/* Chat Panel */}
                <div className="lg:col-span-2 flex flex-col h-[650px] rounded-2xl overflow-hidden border border-slate-200 dark:border-slate-800/80 bg-white/70 dark:bg-slate-900/60 backdrop-blur-md shadow-premium">
                  <div className="p-4 bg-slate-50 dark:bg-slate-900/80 border-b border-slate-200 dark:border-slate-800/80 flex items-center gap-3">
                    <div className="w-10 h-10 rounded-full bg-blue-100 dark:bg-blue-950/80 text-blue-600 dark:text-blue-400 flex items-center justify-center shadow-inner">
                      <Bot className="w-5 h-5" />
                    </div>
                    <div>
                      <h3 className="font-bold text-sm text-slate-800 dark:text-slate-200 font-display">LangGraph ReAct Assistant</h3>
                      <p className="text-slate-400 text-xs">Converses, searches OCR codes, tracks hours, and queries historical sessions.</p>
                    </div>
                  </div>

                  {/* Chat Message Stream */}
                  <div ref={chatLogsRef} className="flex-1 overflow-y-auto p-4 space-y-4 bg-slate-50/50 dark:bg-slate-950/40">
                    {chatMessages.length === 0 ? (
                      <div className="h-full flex flex-col items-center justify-center text-center p-6 space-y-4">
                        <div className="w-14 h-14 rounded-full bg-blue-50 dark:bg-slate-900 text-blue-500 dark:text-blue-400 flex items-center justify-center border border-blue-100 dark:border-blue-950 shadow-inner">
                          <Sparkles className="w-6 h-6 animate-pulse" />
                        </div>
                        <h4 className="font-bold text-base text-slate-700 dark:text-slate-300 font-display">Ask anything about your past computer activity</h4>
                        <p className="text-slate-400 text-xs max-w-md leading-relaxed">
                          The local AI Agent can traverse metadata tags, full screenshots, OCR logs, and ActivityWatch window state. Try clicking a shortcut below:
                        </p>
                        
                        {/* Prompt Suggestions */}
                        <div className="flex flex-col gap-2 max-w-md w-full pt-2">
                          <button
                            onClick={() => setAgentPrompt('Which files or repositories was I editing yesterday?')}
                            className="text-left text-xs bg-white dark:bg-slate-900/80 border border-slate-200 dark:border-slate-800 hover:border-blue-400 dark:hover:border-blue-500/50 hover:bg-blue-50/30 dark:hover:bg-blue-950/20 py-2.5 px-4 rounded-xl text-slate-600 dark:text-slate-300 transition-all font-medium flex items-center gap-2 group shadow-sm"
                          >
                            <Compass className="w-3.5 h-3.5 text-blue-500 shrink-0" />
                            <span>"Which files or repos was I editing yesterday?"</span>
                            <ArrowRight className="w-3 h-3 text-slate-400 ml-auto opacity-0 group-hover:opacity-100 group-hover:translate-x-0.5 transition-all" />
                          </button>

                          <button
                            onClick={() => setAgentPrompt('A couple of days ago I was browsing the web for sneakers, can you tell me which site had the purple sneakers?')}
                            className="text-left text-xs bg-white dark:bg-slate-900/80 border border-slate-200 dark:border-slate-800 hover:border-blue-400 dark:hover:border-blue-500/50 hover:bg-blue-50/30 dark:hover:bg-blue-950/20 py-2.5 px-4 rounded-xl text-slate-600 dark:text-slate-300 transition-all font-medium flex items-center gap-2 group shadow-sm"
                          >
                            <Compass className="w-3.5 h-3.5 text-blue-500 shrink-0" />
                            <span>"Which site had the purple sneakers?"</span>
                            <ArrowRight className="w-3 h-3 text-slate-400 ml-auto opacity-0 group-hover:opacity-100 group-hover:translate-x-0.5 transition-all" />
                          </button>

                          <button
                            onClick={() => setAgentPrompt('How much time did I spend on project PRJ-2026-042 today?')}
                            className="text-left text-xs bg-white dark:bg-slate-900/80 border border-slate-200 dark:border-slate-800 hover:border-blue-400 dark:hover:border-blue-500/50 hover:bg-blue-50/30 dark:hover:bg-blue-950/20 py-2.5 px-4 rounded-xl text-slate-600 dark:text-slate-300 transition-all font-medium flex items-center gap-2 group shadow-sm"
                          >
                            <Compass className="w-3.5 h-3.5 text-blue-500 shrink-0" />
                            <span>"How much time did I spend on PRJ-2026-042?"</span>
                            <ArrowRight className="w-3 h-3 text-slate-400 ml-auto opacity-0 group-hover:opacity-100 group-hover:translate-x-0.5 transition-all" />
                          </button>
                        </div>
                      </div>
                    ) : (
                      chatMessages.map((msg, index) => (
                        <div key={index} className={`flex gap-3 max-w-[85%] ${msg.role === 'user' ? 'ml-auto flex-row-reverse' : 'mr-auto'}`}>
                          <div className={`w-8.5 h-8.5 rounded-full flex items-center justify-center shrink-0 border ${
                            msg.role === 'user' 
                              ? 'bg-blue-600 border-blue-500 text-white' 
                              : 'bg-slate-200 dark:bg-slate-800 border-slate-300 dark:border-slate-700/60 text-slate-700 dark:text-slate-300'
                          }`}>
                            {msg.role === 'user' ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
                          </div>
                          <div className={`p-3.5 rounded-2xl shadow-sm text-sm border ${
                            msg.role === 'user'
                              ? 'bg-blue-600 border-blue-500 text-white rounded-tr-none'
                              : 'bg-white dark:bg-slate-900/80 border-slate-200 dark:border-slate-800/80 text-slate-800 dark:text-slate-200 rounded-tl-none'
                          }`}>
                            <div className="text-[10px] font-bold opacity-60 tracking-wider uppercase mb-1">{msg.role === 'user' ? 'You' : 'Agent Assistant'}</div>
                            <div className="space-y-2">{renderMessageContent(msg.content)}</div>
                          </div>
                        </div>
                      ))
                    )}

                    {/* Agent Thinking Loader */}
                    {querying && (
                      <div className="flex gap-3 max-w-[80%] mr-auto items-start">
                        <div className="w-8.5 h-8.5 rounded-full bg-slate-200 dark:bg-slate-800 text-slate-600 dark:text-slate-400 flex items-center justify-center shrink-0 border border-slate-300 dark:border-slate-700/60">
                          <Bot className="w-4 h-4 animate-spin" />
                        </div>
                        <div className="p-3.5 rounded-2xl bg-white dark:bg-slate-900/80 border border-slate-200 dark:border-slate-800/80 rounded-tl-none text-sm text-slate-500 dark:text-slate-400 shadow-sm flex items-center gap-3">
                          <div className="flex space-x-1">
                            <span className="w-2 h-2 rounded-full bg-blue-500 animate-bounce" style={{ animationDelay: '0ms' }}></span>
                            <span className="w-2 h-2 rounded-full bg-blue-500 animate-bounce" style={{ animationDelay: '150ms' }}></span>
                            <span className="w-2 h-2 rounded-full bg-blue-500 animate-bounce" style={{ animationDelay: '300ms' }}></span>
                          </div>
                          <span className="text-xs">Executing local tools and model reasoning...</span>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Chat Input form */}
                  <div className="p-4 border-t border-slate-200 dark:border-slate-800/80 bg-slate-50/50 dark:bg-slate-900/50">
                    <form onSubmit={submitAgentQuery} className="flex gap-2">
                      <input
                        type="text"
                        value={agentPrompt}
                        onChange={(e) => setAgentPrompt(e.target.value)}
                        placeholder="Ask a question about your screen history, codes, or active projects..."
                        className={`flex-1 rounded-full px-5 py-3 text-sm focus:outline-none ${
                          darkMode ? 'glass-input-dark' : 'glass-input'
                        }`}
                        disabled={querying}
                      />
                      <button
                        type="submit"
                        disabled={querying || !agentPrompt.trim()}
                        className="bg-blue-600 hover:bg-blue-500 text-white rounded-full w-12 h-12 flex items-center justify-center transition-all shadow-md hover:shadow-lg hover:-translate-y-0.5 disabled:opacity-50 disabled:hover:translate-y-0 disabled:shadow-none shrink-0"
                      >
                        {querying ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                      </button>
                    </form>
                  </div>
                </div>

                {/* Queue Stats Side panel */}
                <div className="space-y-6">
                  <div className="glass-card-dark border-slate-200/20 dark:border-slate-800/50 bg-white/70 dark:bg-slate-900/60 p-5 rounded-2xl border shadow-premium">
                    <h3 className="font-bold text-base text-slate-800 dark:text-slate-100 font-display mb-4 flex items-center gap-2">
                      <Database className="w-4 h-4 text-blue-500" /> System Pipeline Queue
                    </h3>

                    <div className="space-y-4">
                      <div className="flex justify-between items-center text-sm">
                        <span className="text-slate-500 dark:text-slate-400 font-medium">Screenshots Pending</span>
                        <span className="px-2.5 py-1 bg-amber-100 dark:bg-amber-950/80 text-amber-700 dark:text-amber-300 rounded-full text-xs font-extrabold shadow-inner border border-amber-200/30">
                          {status.pending_queue_size}
                        </span>
                      </div>
                      
                      <div className="flex justify-between items-center text-sm">
                        <span className="text-slate-500 dark:text-slate-400 font-medium">Screenshots Indexed</span>
                        <span className="px-2.5 py-1 bg-emerald-100 dark:bg-emerald-950/80 text-emerald-700 dark:text-emerald-300 rounded-full text-xs font-extrabold shadow-inner border border-emerald-200/30">
                          {status.processed_database_size}
                        </span>
                      </div>

                      <div className="pt-2">
                        <div className="w-full h-2.5 bg-slate-200 dark:bg-slate-800 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-blue-500 rounded-full transition-all duration-500"
                            style={{ width: `${(status.processed_database_size / (status.processed_database_size + status.pending_queue_size || 1)) * 100}%` }}
                          ></div>
                        </div>
                      </div>

                      {status.system_load && (
                        <div className="grid grid-cols-2 gap-3 pt-3 border-t border-slate-200 dark:border-slate-800/60 text-xs">
                          <div className="space-y-1 p-2 bg-slate-50 dark:bg-slate-950/40 rounded-xl border border-slate-200/50 dark:border-slate-800/50">
                            <span className="text-slate-400">Host CPU</span>
                            <div className="font-bold text-slate-700 dark:text-slate-200 flex items-center gap-1">
                              <Cpu className="w-3.5 h-3.5 text-blue-500" /> {status.system_load.cpu_percent}%
                            </div>
                          </div>
                          <div className="space-y-1 p-2 bg-slate-50 dark:bg-slate-950/40 rounded-xl border border-slate-200/50 dark:border-slate-800/50">
                            <span className="text-slate-400">Host RAM</span>
                            <div className="font-bold text-slate-700 dark:text-slate-200 flex items-center gap-1">
                              <Activity className="w-3.5 h-3.5 text-purple-500" /> {status.system_load.memory_percent}%
                            </div>
                          </div>
                        </div>
                      )}

                      <div className="p-3 bg-blue-50/50 dark:bg-blue-950/15 rounded-xl border border-blue-100/30 dark:border-blue-900/20 text-xs text-slate-500 dark:text-slate-400 flex items-start gap-2 leading-relaxed">
                        <Info className="w-4 h-4 text-blue-500 shrink-0 mt-0.5" />
                        <div>
                          <strong className="text-slate-700 dark:text-slate-300">Resource Saving Queue:</strong> Screenshots are batched and processed ONLY when system CPU is low to avoid gaming or build disruption.
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="relative overflow-hidden p-5 rounded-2xl border border-blue-500/10 bg-gradient-to-br from-blue-600/90 to-indigo-700/90 text-white shadow-premium">
                    <div className="absolute top-0 right-0 w-32 h-32 bg-white/5 rounded-full translate-x-10 -translate-y-10 blur-2xl"></div>
                    <h3 className="font-bold text-base font-display mb-2 flex items-center gap-2"><Shield className="w-5 h-5 opacity-90" /> 100% Local Privacy</h3>
                    <p className="text-slate-100 text-xs opacity-85 leading-relaxed">
                      All calculations are performed completely on-device. Images are never uploaded to remote servers. All analysis models run locally via Ollama, guaranteeing absolute data sovereignty.
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* TAB 2: SCREENSHOT LIBRARY & SEARCH */}
            {activeTab === 'gallery' && (
              <div className="space-y-6">
                
                {/* Search Header */}
                <div className="glass-card-dark border-slate-200/20 dark:border-slate-800/50 bg-white/70 dark:bg-slate-900/60 p-4 rounded-2xl border shadow-premium">
                  <form onSubmit={(e) => { e.preventDefault(); fetchHistory() }} className="flex flex-col sm:flex-row items-center gap-3">
                    <div className="relative flex-1 w-full">
                      <Search className="w-4 h-4 text-slate-400 absolute left-4 top-1/2 -translate-y-1/2" />
                      <input
                        type="text"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        placeholder="Search semantic features (e.g., 'coding in python' or 'purple dashboard text')..."
                        className={`w-full pl-11 pr-5 py-2.5 text-sm rounded-xl focus:outline-none ${
                          darkMode ? 'glass-input-dark' : 'glass-input'
                        }`}
                      />
                    </div>
                    <div className="flex gap-2 w-full sm:w-auto">
                      <button
                        type="submit"
                        disabled={loadingHistory}
                        className="flex-1 sm:flex-initial bg-blue-600 hover:bg-blue-500 text-white text-sm font-semibold py-2.5 px-6 rounded-xl flex items-center justify-center gap-2 transition-all shadow shadow-blue-600/10 disabled:opacity-50"
                      >
                        <RefreshCw className={`w-4 h-4 ${loadingHistory ? 'animate-spin' : ''}`} />
                        Search
                      </button>
                      <button
                        type="button"
                        onClick={clearSearch}
                        className="bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 text-sm font-semibold py-2.5 px-4 rounded-xl transition-all border border-slate-200 dark:border-slate-700"
                      >
                        Clear
                      </button>
                    </div>
                  </form>
                </div>

                {/* Screenshots Gallery Grid */}
                {loadingHistory ? (
                  <div className="text-center py-20">
                    <div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto"></div>
                    <p className="text-slate-400 text-sm mt-4">Consulting local LanceDB vector search...</p>
                  </div>
                ) : historyRecords.length === 0 ? (
                  <div className="text-center py-16 bg-white dark:bg-slate-900/50 rounded-2xl border border-slate-200 dark:border-slate-800/80 shadow-premium max-w-2xl mx-auto space-y-3">
                    <ImageIcon className="w-12 h-12 text-slate-300 dark:text-slate-700 mx-auto" />
                    <h3 className="font-bold text-lg dark:text-slate-300 font-display">No screen captures found</h3>
                    <p className="text-slate-400 text-sm max-w-md mx-auto px-4 leading-relaxed">
                      Capture logs are created every minute while active. Make sure the watcher is active and the bulk processor has parsed files.
                    </p>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    {historyRecords.map((rec) => (
                      <div
                        key={rec.id || Math.random().toString()}
                        className="group flex flex-col bg-white dark:bg-slate-900/60 rounded-2xl overflow-hidden border border-slate-200 dark:border-slate-800/80 shadow-sm hover:shadow-premium hover:-translate-y-1 transition-all duration-300"
                      >
                        {/* Image Frame Wrapper */}
                        <div 
                          className="relative h-48 bg-slate-950 flex items-center justify-center overflow-hidden cursor-pointer"
                          onClick={() => openImageLightbox(rec)}
                        >
                          {rec.image_filename ? (
                            <>
                              <img
                                src={`${API_BASE}/api/screenshots/${rec.image_filename}`}
                                className="w-full h-full object-cover group-hover:scale-105 transition-all duration-500"
                                alt="Computer desktop capture"
                                loading="lazy"
                              />
                              <div className="absolute inset-0 bg-slate-950/40 opacity-0 group-hover:opacity-100 flex items-center justify-center transition-all">
                                <div className="w-11 h-11 bg-white/15 backdrop-blur-md rounded-full flex items-center justify-center shadow-lg border border-white/20 scale-90 group-hover:scale-100 transition-all">
                                  <Maximize2 className="w-5 h-5 text-white" />
                                </div>
                              </div>
                            </>
                          ) : (
                            <div className="absolute inset-0 bg-gradient-to-br from-slate-900 to-slate-950 flex flex-col items-center justify-center p-4 text-center">
                              <Archive className="w-10 h-10 text-slate-600 mb-2 opacity-50" />
                              <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">Archived Metadata</span>
                              <span className="text-[10px] text-slate-600 mt-1">Screenshot purged (14-day storage threshold)</span>
                            </div>
                          )}

                          {/* Float Metadata Badges */}
                          <span className="absolute bottom-2 right-2 bg-slate-950/85 backdrop-blur-sm text-slate-200 text-[10px] font-semibold px-2 py-1 rounded-md tracking-wide">
                            {formatTimestamp(rec.timestamp)}
                          </span>

                          {rec.project_number && (
                            <span className="absolute top-2 left-2 bg-blue-600 text-white text-[10px] font-extrabold px-2.5 py-1 rounded-md shadow-md">
                              {rec.project_number}
                            </span>
                          )}

                          {rec.distance !== undefined && (
                            <span className="absolute top-2 right-2 bg-purple-600 text-white text-[9px] font-bold px-1.5 py-0.5 rounded-md shadow">
                              Match: {Math.max(0, Math.round((1 - rec.distance) * 100))}%
                            </span>
                          )}
                        </div>

                        {/* Card Body details */}
                        <div className="p-4 flex-1 flex flex-col justify-between space-y-4">
                          <div>
                            <div className="flex items-center gap-2 mb-2">
                              <span className="px-2 py-0.5 bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700/60 rounded text-[11px] font-bold text-slate-600 dark:text-slate-400 max-w-[150px] truncate">
                                {rec.app_name}
                              </span>
                              {rec.is_afk && <span className="px-1.5 py-0.5 bg-rose-500/20 text-rose-500 text-[10px] font-extrabold rounded">AFK</span>}
                            </div>

                            <h4 className="font-bold text-sm text-slate-800 dark:text-slate-100 line-clamp-1 mb-1.5" title={rec.window_title}>
                              {rec.window_title}
                            </h4>

                            <p className="text-slate-400 text-xs leading-relaxed line-clamp-3 mb-2" title={rec.description}>
                              {rec.description}
                            </p>

                            {/* OCR snippet if present */}
                            {rec.ocr_text && (
                              <div className="mt-3 bg-slate-50 dark:bg-slate-950/40 p-2.5 rounded-xl border border-slate-200/50 dark:border-slate-800/60">
                                <button
                                  onClick={() => setExpandedOcrCardId(expandedOcrCardId === rec.id ? null : rec.id)}
                                  className="w-full text-left flex items-center justify-between text-[10px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400"
                                >
                                  <span className="flex items-center gap-1.5"><FileText className="w-3.5 h-3.5 text-blue-500" /> Extracted OCR Text</span>
                                  <span className="text-blue-500 font-semibold">{expandedOcrCardId === rec.id ? 'Collapse' : 'Expand'}</span>
                                </button>
                                <div className={`transition-all duration-200 overflow-hidden ${expandedOcrCardId === rec.id ? 'max-h-48 mt-2 overflow-y-auto' : 'max-h-5 overflow-hidden'}`}>
                                  <pre className="text-[10px] font-mono text-slate-600 dark:text-slate-400 whitespace-pre-wrap leading-normal block pt-1 select-all">
                                    {rec.ocr_text}
                                  </pre>
                                </div>
                              </div>
                            )}
                          </div>

                          {/* Tag Badges */}
                          {rec.tags.length > 0 && (
                            <div className="flex flex-wrap gap-1 pt-2 border-t border-slate-100 dark:border-slate-800/40">
                              {rec.tags.map((tag) => (
                                <span key={tag} className="text-[10px] font-bold bg-blue-500/10 text-blue-600 dark:text-blue-400 px-1.5 py-0.5 rounded-md">
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
                <div className="lg:col-span-2 glass-card-dark border-slate-200/20 dark:border-slate-800/50 bg-white/70 dark:bg-slate-900/60 p-6 rounded-2xl border shadow-premium h-fit space-y-4">
                  <div>
                    <h3 className="font-bold text-lg text-slate-800 dark:text-slate-100 font-display">Tracked Hours by Project Guidelines</h3>
                    <p className="text-slate-400 text-xs mt-1">
                      Durations are compiled automatically by scanning screenshots, window focus records, and evaluating match criteria.
                    </p>
                  </div>

                  {projectsList.length === 0 ? (
                    <p className="text-slate-500 text-sm">No active guidelines defined.</p>
                  ) : (
                    <div className="space-y-4 pt-2">
                      {projectsList.map((proj) => (
                        <div
                          key={proj.project_number}
                          className="p-4 bg-slate-50 dark:bg-slate-950/40 rounded-xl border border-slate-200/60 dark:border-slate-800/80 hover:bg-slate-100/50 dark:hover:bg-slate-900/40 transition-colors space-y-3"
                        >
                          <div className="flex items-center justify-between gap-3">
                            <div className="flex items-center gap-2">
                              <span className="bg-blue-600 text-white text-xs font-extrabold px-3 py-1 rounded-md shadow-sm">
                                {proj.project_number}
                              </span>
                              <strong className="text-slate-700 dark:text-slate-200 text-sm font-display">{proj.description}</strong>
                            </div>
                            <span className="text-base font-extrabold text-blue-600 dark:text-blue-400">{proj.tracked_hours || 0} h</span>
                          </div>

                          <p className="text-slate-400 text-xs leading-relaxed">{proj.work_entailment}</p>

                          <div className="space-y-1">
                            <div className="w-full h-2 bg-slate-200 dark:bg-slate-800 rounded-full overflow-hidden">
                              <div
                                className="h-full bg-blue-500 rounded-full transition-all duration-500"
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
                <div className="glass-card-dark border-slate-200/20 dark:border-slate-800/50 bg-white/70 dark:bg-slate-900/60 p-5 rounded-2xl border shadow-premium h-fit space-y-4">
                  <div>
                    <h3 className="font-bold text-base text-slate-800 dark:text-slate-100 font-display">Configure Project Guidelines</h3>
                    <p className="text-slate-400 text-xs mt-1 leading-relaxed">
                      Define project guidelines as JSON. This criteria dictates how the LLM vision system automatically categorizes and segments newly indexed screenshots.
                    </p>
                  </div>

                  <textarea
                    value={projectsJsonInput}
                    onChange={(e) => setProjectsJsonInput(e.target.value)}
                    rows={12}
                    className="w-full p-3 font-mono text-xs text-slate-800 dark:text-emerald-400 bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800/80 rounded-xl focus:outline-none focus:ring-1 focus:ring-blue-500"
                  ></textarea>

                  <button
                    onClick={saveProjectsJson}
                    disabled={savingProjects}
                    className="w-full bg-blue-600 hover:bg-blue-500 text-white font-semibold py-2.5 px-4 rounded-xl flex items-center justify-center gap-2 transition-all shadow shadow-blue-600/15 disabled:opacity-50"
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
            <div className="fixed inset-0 bg-slate-950/85 backdrop-blur-md" onClick={() => setLightboxOpen(false)}></div>
            
            <div className="relative z-10 max-w-4.5xl w-full bg-slate-900 rounded-2xl overflow-hidden border border-slate-800 shadow-2xl flex flex-col">
              
              {/* Close Button */}
              <button
                onClick={() => setLightboxOpen(false)}
                className="absolute top-4 right-4 z-20 w-8.5 h-8.5 rounded-full bg-slate-950/50 hover:bg-slate-950 text-slate-400 hover:text-white flex items-center justify-center border border-white/5 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>

              {/* Image Frame */}
              <div className="bg-slate-950 flex justify-center items-center p-3 border-b border-slate-850 h-[380px] md:h-[450px]">
                {selectedRecord.image_filename ? (
                  <img
                    src={`${API_BASE}/api/screenshots/${selectedRecord.image_filename}`}
                    className="max-w-full max-h-full rounded-lg object-contain"
                    alt="Desktop Full View"
                  />
                ) : (
                  <div className="text-center p-8 space-y-3">
                    <Archive className="w-16 h-16 text-slate-700 mx-auto" />
                    <h3 className="font-bold text-xl text-slate-400 font-display">Screenshot Image Archived</h3>
                    <p className="text-slate-500 text-sm max-w-md mx-auto leading-relaxed">
                      This screen capture occurred more than 14 days ago. To preserve disk footprint, the binary image file has been cleanly purged from disk, but its analysis descriptions, tags, and semantic indexing vector are retained permanently.
                    </p>
                  </div>
                )}
              </div>

              {/* Text metadata footer content */}
              <div className="p-5 md:p-6 space-y-4 max-h-[220px] overflow-y-auto">
                <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="bg-blue-600 text-white font-extrabold px-3 py-1 rounded-md">
                      {selectedRecord.project_number || 'Unclassified'}
                    </span>
                    <span className="bg-slate-800 text-slate-300 font-semibold px-2.5 py-1 rounded-md border border-slate-700/50">
                      {selectedRecord.app_name}
                    </span>
                  </div>
                  <span className="text-slate-500 font-medium">{formatTimestamp(selectedRecord.timestamp)}</span>
                </div>

                <div className="space-y-1">
                  <h4 className="font-bold text-base text-white font-display leading-tight">{selectedRecord.window_title}</h4>
                  <p className="text-slate-300 text-sm leading-relaxed">{selectedRecord.description}</p>
                </div>

                {/* Lightbox full OCR text preview */}
                {selectedRecord.ocr_text && (
                  <div className="bg-slate-950 p-4 rounded-xl border border-slate-800/80 space-y-2">
                    <h5 className="text-[10px] font-bold uppercase tracking-wider text-slate-500 flex items-center gap-1.5">
                      <FileText className="w-4 h-4 text-blue-500" /> Fully Parsed Code &amp; Extracted Text (OCR)
                    </h5>
                    <pre className="text-xs font-mono text-emerald-400 whitespace-pre-wrap select-all max-h-48 overflow-y-auto border border-slate-900 p-2 rounded-lg bg-slate-900/60 leading-normal">
                      {selectedRecord.ocr_text}
                    </pre>
                  </div>
                )}

                {/* Tag items */}
                {selectedRecord.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 pt-2 border-t border-slate-800">
                    {selectedRecord.tags.map((tag) => (
                      <span key={tag} className="text-xs font-bold bg-slate-800 border border-slate-700 text-slate-400 px-2 py-0.5 rounded-md">
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
