import React, { useRef, useEffect } from 'react'
import {
  Bot,
  User,
  Send,
  Compass,
  ArrowRight,
  RefreshCw,
  Activity,
  Folder,
  Maximize2,
  CornerDownLeft,
  Paperclip,
  CheckCircle2,
  Terminal
} from 'lucide-react'
import type { ChatMessage, HistoryRecord, Project } from '../types'

interface AgentTabProps {
  chatMessages: ChatMessage[]
  querying: boolean
  agentPrompt: string
  setAgentPrompt: (val: string) => void
  submitAgentQuery: (e?: React.FormEvent) => void
  historyRecords: HistoryRecord[]
  projectsList: Project[]
  openImageLightbox: (rec: HistoryRecord) => void
  API_BASE: string
}

export const AgentTab: React.FC<AgentTabProps> = ({
  chatMessages,
  querying,
  agentPrompt,
  setAgentPrompt,
  submitAgentQuery,
  historyRecords,
  projectsList,
  openImageLightbox,
  API_BASE
}) => {
  const chatLogsRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (chatLogsRef.current) {
      chatLogsRef.current.scrollTop = chatLogsRef.current.scrollHeight
    }
  }, [chatMessages, querying])

  // A2UI Generative Parser: Extract project keys (e.g. PRJ-2026-042)
  const parseProjectKeys = (text: string): string[] => {
    const regex = /PRJ-\d{4}-\d{3}/gi
    const matches = text.match(regex)
    if (!matches) return []
    return Array.from(new Set(matches.map(m => m.toUpperCase())))
  }

  // A2UI Generative Parser: Extract screenshot filename patterns
  const parseScreenshots = (text: string): string[] => {
    const regex = /[a-f0-9-_\d]+\.png/gi
    const matches = text.match(regex)
    if (!matches) return []
    return Array.from(new Set(matches.map(m => m.trim())))
  }

  // A2UI Generative Component: Render Project Ledger Row
  const renderA2UIProjectCard = (key: string) => {
    const project = projectsList.find(p => p.project_number === key)
    return (
      <div key={key} className="mt-3 p-4 bg-surface-container-low border border-primary/20 rounded-lg flex flex-col md:flex-row md:items-center justify-between gap-4 font-sans select-none">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <Folder className="w-4 h-4 text-primary" />
            <span className="text-[12px] font-bold text-neutral-dark font-mono bg-surface-container-lowest px-2 py-0.5 rounded border border-surface-container-high">
              {key}
            </span>
            <span className="text-[10px] font-semibold text-primary uppercase tracking-wider bg-accent-surface border border-primary/10 px-1.5 py-0.5 rounded">
              A2UI Active Card
            </span>
          </div>
          <p className="text-body-sm text-neutral-dark font-medium leading-relaxed">
            {project ? project.description : 'Project definition loaded from system guidelines.'}
          </p>
          {project && (
            <p className="text-technical-sm text-text-secondary">
              Entailment: {project.work_entailment}
            </p>
          )}
        </div>

        {project && (
          <div className="flex flex-col items-end gap-1.5 shrink-0">
            <span className="text-body-sm text-neutral-dark font-medium">
              Tracked: <strong className="font-mono text-primary font-bold">{project.tracked_hours.toFixed(1)} hrs</strong>
            </span>
            <div className="w-24 h-1.5 bg-surface-container rounded-full overflow-hidden">
              <div
                className="h-full bg-primary rounded-full"
                style={{ width: `${Math.min((project.tracked_hours / 40) * 100, 100)}%` }}
              ></div>
            </div>
          </div>
        )}
      </div>
    )
  }

  // A2UI Generative Component: Render Screenshot citation thumbnail
  const renderA2UIScreenshotCard = (filename: string) => {
    const record = historyRecords.find(r => r.image_filename === filename)
    return (
      <div key={filename} className="mt-3 p-3 bg-surface-container-lowest border border-surface-container-high rounded-lg flex items-center justify-between gap-4 font-sans select-none">
        <div className="flex items-center gap-3">
          <div className="relative w-16 h-11 bg-surface-container rounded border border-surface-container-high overflow-hidden shrink-0">
            <img
              src={`${API_BASE}/api/screenshots/${filename}`}
              className="w-full h-full object-cover"
              alt="Citation preview"
              onError={(e) => {
                // If local image is purged
                (e.target as HTMLElement).style.display = 'none'
              }}
            />
          </div>
          <div className="space-y-0.5 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-bold text-neutral-dark font-mono truncate max-w-[150px]">
                {filename}
              </span>
              <span className="text-[9px] font-bold text-success-green uppercase tracking-wider bg-success-green/10 border border-success-green/20 px-1 py-0.5 rounded font-mono">
                A2UI Citation
              </span>
            </div>
            <p className="text-[11px] text-text-secondary truncate max-w-[250px] md:max-w-[400px]">
              {record ? record.window_title : 'Desktop Activity Screenshot Reference'}
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={() => {
            const rec = record || {
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
          className="text-text-secondary hover:text-primary p-1.5 hover:bg-surface-container rounded border border-surface-container-high flex items-center justify-center transition-colors cursor-pointer shrink-0"
          title="Zoom Screenshot"
        >
          <Maximize2 className="w-3.5 h-3.5" />
        </button>
      </div>
    )
  }

  const renderMessageContent = (text: string) => {
    if (!text) return null

    const parts = text.split(/(```[\s\S]*?```)/g)

    return (
      <div className="space-y-2">
        {parts.map((part, index) => {
          if (part.startsWith('```') && part.endsWith('```')) {
            const match = part.match(/```(\w*)\n([\s\S]*?)```/)
            const lang = match ? match[1] : ''
            const code = match ? match[2] : part.slice(3, -3)
            return (
              <pre
                key={index}
                className="bg-surface-container-low text-neutral-dark p-4 rounded-lg my-3 text-technical-sm overflow-x-auto border border-surface-container-high font-mono"
              >
                {lang && (
                  <div className="text-[10px] text-text-secondary font-messina font-semibold uppercase tracking-wider mb-2 border-b border-surface-container-high pb-1">
                    {lang}
                  </div>
                )}
                <code className="block whitespace-pre select-all font-mono leading-normal">{code}</code>
              </pre>
            )
          }

          const lines = part.split('\n')
          return lines.map((line, lIdx) => {
            const regex = /(\*\*.*?\*\*|`.*?`)/gi
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
                  <code
                    key={tIdx}
                    className="bg-surface-container text-danger-primary px-1.5 py-0.5 rounded font-mono text-technical-sm border border-surface-container-high"
                  >
                    {token.slice(1, -1)}
                  </code>
                )
              }
              return token
            })

            return (
              <p
                key={lIdx}
                className={`leading-relaxed text-body-md text-neutral-dark ${
                  lIdx === lines.length - 1 ? 'mb-0' : 'mb-2'
                }`}
              >
                {lineElements}
              </p>
            )
          })
        })}

        {/* Dynamic A2UI Generative Components Section */}
        {parseProjectKeys(text).map(renderA2UIProjectCard)}
        {parseScreenshots(text).map(renderA2UIScreenshotCard)}
      </div>
    )
  }

  return (
    <div className="font-sans space-y-6">
      {/* Untitled UI Page Header */}
      <div className="border-b border-surface-container-high pb-5">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="text-[11px] font-semibold text-primary uppercase tracking-wider bg-accent-surface border border-primary/10 px-2.5 py-0.5 rounded font-mono select-none">
                AI Cognitive Assistant
              </span>
              <span className="w-1.5 h-1.5 rounded-full bg-success-green animate-pulse" />
              <span className="text-[11px] font-medium text-text-secondary">AG-UI Active</span>
            </div>
            <h2 className="text-2xl md:text-3xl font-bold text-neutral-dark tracking-tight">
              Ask Memory Agent
            </h2>
            <p className="text-text-secondary text-body-md mt-1.5 max-w-2xl leading-relaxed">
              Query your past screen activities using natural language. The local agent resolves database search logs, tracks project metrics, and maps coordinates automatically.
            </p>
          </div>
        </div>
      </div>

      {/* Untitled UI Messenger Panel */}
      <div className="flex flex-col h-[650px] rounded-xl border border-surface-container-high bg-surface-container-lowest overflow-hidden">
        {/* Messenger Header */}
        <div className="p-4 bg-surface-container-low border-b border-surface-container-high flex items-center justify-between select-none">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-surface-container-lowest border border-surface-container-high text-primary flex items-center justify-center shrink-0">
              <Bot className="w-5.5 h-5.5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="font-bold text-headline-sm text-neutral-dark">
                  Local Memory Assistant
                </h2>
                <span className="px-2 py-0.5 text-[9px] font-bold text-primary bg-accent-surface border border-primary/15 rounded-full font-mono">
                  AG-UI Bridge
                </span>
              </div>
              <p className="text-text-secondary text-[11px] font-medium">
                LangGraph ReAct Loop • Powered by Local Models
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            <span className="inline-flex items-center gap-1.5 text-[10px] font-semibold font-mono text-success-green bg-success-green/10 px-2.5 py-1 rounded border border-success-green/15">
              <CheckCircle2 className="w-3 h-3" /> AG-UI Connected
            </span>
            <span className="hidden md:inline-flex items-center gap-1.5 text-[10px] font-semibold font-mono text-primary bg-accent-surface px-2.5 py-1 rounded border border-primary/15">
              <Activity className="w-3 h-3" /> A2UI Generative Enabled
            </span>
          </div>
        </div>

        {/* Chat Message Stream */}
        <div ref={chatLogsRef} className="flex-1 overflow-y-auto p-5 space-y-5 bg-surface-dim">
          {chatMessages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center p-6 space-y-4">
              <div className="w-14 h-14 rounded-full bg-surface-container-lowest text-primary flex items-center justify-center border border-surface-container-high shadow-none">
                <Bot className="w-7 h-7 animate-pulse" />
              </div>
              <div className="space-y-1">
                <h3 className="font-bold text-headline-sm text-neutral-dark">
                  Ask anything about your computer session history
                </h3>
                <p className="text-text-secondary text-body-sm max-w-md leading-relaxed">
                  The local assistant inspects LanceDB tags, raw OCR text blocks, and project guidelines. To begin, ask a question or click a prompt shortcut below:
                </p>
              </div>

              {/* Prompt Suggestions */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 max-w-3xl w-full pt-4">
                <button
                  onClick={() => setAgentPrompt('Which files or repositories was I editing yesterday?')}
                  className="text-left text-action-md font-messina font-semibold bg-surface-container-lowest border border-surface-container-high hover:border-primary hover:bg-surface-container-low p-3.5 rounded-lg text-neutral-dark transition-all flex flex-col justify-between gap-3 group select-none cursor-pointer"
                >
                  <Compass className="w-5 h-5 text-primary shrink-0" />
                  <span className="text-body-sm">"Which files or repos was I editing yesterday?"</span>
                  <span className="text-[10px] text-primary group-hover:text-primary-container font-medium flex items-center gap-1">
                    Ask Prompt <ArrowRight className="w-3 h-3 transition-transform group-hover:translate-x-0.5" />
                  </span>
                </button>

                <button
                  onClick={() =>
                    setAgentPrompt(
                      'A couple of days ago I was browsing the web for sneakers, can you tell me which site had the purple sneakers?'
                    )
                  }
                  className="text-left text-action-md font-messina font-semibold bg-surface-container-lowest border border-surface-container-high hover:border-primary hover:bg-surface-container-low p-3.5 rounded-lg text-neutral-dark transition-all flex flex-col justify-between gap-3 group select-none cursor-pointer"
                >
                  <Compass className="w-5 h-5 text-primary shrink-0" />
                  <span className="text-body-sm">"Which website had the purple sneakers?"</span>
                  <span className="text-[10px] text-primary group-hover:text-primary-container font-medium flex items-center gap-1">
                    Ask Prompt <ArrowRight className="w-3 h-3 transition-transform group-hover:translate-x-0.5" />
                  </span>
                </button>

                <button
                  onClick={() => setAgentPrompt('How much time did I spend on project PRJ-2026-042 today?')}
                  className="text-left text-action-md font-messina font-semibold bg-surface-container-lowest border border-surface-container-high hover:border-primary hover:bg-surface-container-low p-3.5 rounded-lg text-neutral-dark transition-all flex flex-col justify-between gap-3 group select-none cursor-pointer"
                >
                  <Compass className="w-5 h-5 text-primary shrink-0" />
                  <span className="text-body-sm">"How much time did I spend on PRJ-2026-042?"</span>
                  <span className="text-[10px] text-primary group-hover:text-primary-container font-medium flex items-center gap-1">
                    Ask Prompt <ArrowRight className="w-3 h-3 transition-transform group-hover:translate-x-0.5" />
                  </span>
                </button>
              </div>
            </div>
          ) : (
            chatMessages.map((msg, index) => {
              const isUser = msg.role === 'user'
              return (
                <div
                  key={index}
                  className={`flex gap-3.5 max-w-[85%] md:max-w-[75%] ${
                    isUser ? 'ml-auto flex-row-reverse' : 'mr-auto'
                  }`}
                >
                  <div
                    className={`w-9 h-9 rounded-full flex items-center justify-center shrink-0 border select-none ${
                      isUser
                        ? 'bg-primary border-primary text-on-primary'
                        : 'bg-surface-container-lowest border-surface-container-high text-primary'
                    }`}
                  >
                    {isUser ? <User className="w-4.5 h-4.5" /> : <Bot className="w-4.5 h-4.5" />}
                  </div>
                  <div
                    className={`p-4 rounded-2xl text-body-md border transition-all ${
                      isUser
                        ? 'bg-primary border-primary text-on-primary rounded-tr-none shadow-none'
                        : 'bg-surface-container-lowest border-surface-container-high text-neutral-dark rounded-tl-none shadow-none'
                    }`}
                  >
                    <div className={`text-[10px] font-bold font-messina tracking-wider uppercase mb-1.5 select-none ${
                      isUser ? 'text-white/60' : 'text-text-secondary'
                    }`}>
                      {isUser ? 'You' : 'Memory Agent'}
                    </div>
                    <div>{renderMessageContent(msg.content)}</div>
                  </div>
                </div>
              )
            })
          )}

          {/* AG-UI Live Process Steps */}
          {querying && (
            <div className="flex gap-3.5 max-w-[80%] mr-auto items-start">
              <div className="w-9 h-9 rounded-full bg-surface-container-lowest border border-surface-container-high text-primary flex items-center justify-center shrink-0">
                <Bot className="w-4.5 h-4.5 animate-spin" />
              </div>
              <div className="flex flex-col gap-3">
                <div className="p-4 rounded-2xl rounded-tl-none bg-surface-container-lowest border border-surface-container-high text-body-sm text-neutral-dark flex items-center gap-3 shadow-none">
                  <div className="flex space-x-1">
                    <span className="w-2 h-2 rounded-full bg-primary animate-bounce" style={{ animationDelay: '0ms' }}></span>
                    <span className="w-2 h-2 rounded-full bg-primary animate-bounce" style={{ animationDelay: '150ms' }}></span>
                    <span className="w-2 h-2 rounded-full bg-primary animate-bounce" style={{ animationDelay: '300ms' }}></span>
                  </div>
                  <span className="font-semibold text-text-secondary">Generating response via local gemma4 model...</span>
                </div>

                {/* AG-UI Pipeline Steps visualizer */}
                <div className="bg-surface-container-lowest border border-surface-container-high rounded-xl p-3.5 text-technical-sm font-mono space-y-2 select-none">
                  <div className="flex items-center gap-2 text-text-secondary font-bold text-[10px] uppercase tracking-wider font-messina pb-2 border-b border-surface-container-high">
                    <Terminal className="w-3.5 h-3.5 text-primary" />
                    <span>AG-UI Live Graph Protocol Steps</span>
                  </div>
                  <div className="flex items-center gap-2 text-success-green">
                    <span className="w-1.5 h-1.5 rounded-full bg-success-green"></span>
                    <span>[AG-UI] Step 1: Embedding generation (embeddinggemma) - SUCCESS</span>
                  </div>
                  <div className="flex items-center gap-2 text-success-green">
                    <span className="w-1.5 h-1.5 rounded-full bg-success-green"></span>
                    <span>[AG-UI] Step 2: Querying LanceDB semantic coordinate index - SUCCESS</span>
                  </div>
                  <div className="flex items-center gap-2 text-primary animate-pulse">
                    <RefreshCw className="w-3 h-3 animate-spin" />
                    <span>[AG-UI] Step 3: Graph routing state execution & synthesis...</span>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Untitled UI Messaging Input Dock */}
        <div className="p-4 border-t border-surface-container-high bg-surface-container-lowest">
          <form
            onSubmit={(e) => {
              e.preventDefault()
              submitAgentQuery()
            }}
            className="flex items-center gap-3"
          >
            {/* Action Tools Inside Input Container */}
            <div className="flex-1 flex items-center bg-surface-container-low border border-surface-container-high rounded-lg focus-within:border-primary px-3 h-11 transition-all">
              <button
                type="button"
                className="text-text-secondary hover:text-neutral-dark p-1 rounded hover:bg-surface-container transition-colors select-none cursor-pointer"
                title="Add attachment (Local Only)"
              >
                <Paperclip className="w-4 h-4" />
              </button>
              <input
                id="agent-prompt"
                name="agent-prompt"
                type="text"
                value={agentPrompt}
                onChange={(e) => setAgentPrompt(e.target.value)}
                placeholder="Ask a question about your screen history, codes, or active projects..."
                className="flex-1 bg-transparent border-0 outline-none text-body-md text-on-surface px-3 placeholder:text-text-secondary disabled:opacity-50"
                disabled={querying}
              />
              <span className="hidden md:inline-flex items-center gap-1.5 text-[9px] font-semibold text-text-secondary bg-surface-container-lowest border border-surface-container-high px-2 py-0.5 rounded font-mono select-none mr-1.5">
                <CornerDownLeft className="w-2.5 h-2.5" /> ENTER
              </span>
            </div>

            <button
              type="submit"
              disabled={querying || !agentPrompt.trim()}
              className="bg-primary hover:bg-primary-container text-on-primary rounded-lg h-11 px-5 flex items-center justify-center gap-2 font-messina font-bold text-action-md transition-colors disabled:opacity-50 select-none cursor-pointer"
            >
              {querying ? (
                <RefreshCw className="w-4 h-4 animate-spin" />
              ) : (
                <>
                  <span>Send</span>
                  <Send className="w-4 h-4" />
                </>
              )}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
