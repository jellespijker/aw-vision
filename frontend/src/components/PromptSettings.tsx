import React, { useState, useEffect, useRef } from 'react'
import axios from 'axios'
import {
  FileTerminal,
  Loader2,
  CheckCircle2,
  RotateCcw,
  ChevronDown,
  ChevronRight,
  Braces,
  BadgeCheck,
  FlaskConical,
  Check,
  X,
  AlertCircle
} from 'lucide-react'

interface PromptSettingsProps {
  showNotification: (text: string, type: 'success' | 'danger') => void
}

interface PromptDef {
  id: string
  label: string
  group: string
  description: string
  placeholders: string[]
  template: string
  default_template: string
  is_customized: boolean
}

interface EvalResultRow {
  id: string
  window_title: string
  app_name: string
  human_project: string | null
  predicted_project: string | null
  match_type: string | null
  match: boolean
  error: string | null
}

interface EvalStatus {
  is_running: boolean
  prompt_id: string | null
  total: number
  completed: number
  results: EvalResultRow[]
  accuracy: number | null
  error: string | null
}

const EVALUABLE = ['gemini_combined', 'local_synthesis']

export const PromptSettings: React.FC<PromptSettingsProps> = ({ showNotification }) => {
  const [prompts, setPrompts] = useState<PromptDef[]>([])
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState<boolean>(true)
  const [savingId, setSavingId] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [evalStatus, setEvalStatus] = useState<EvalStatus | null>(null)
  const evalPollRef = useRef<any>(null)

  useEffect(() => {
    loadPrompts()
    // Pick up an evaluation that may already be running server-side
    pollEvalStatus()
    return () => {
      if (evalPollRef.current) clearInterval(evalPollRef.current)
    }
  }, [])

  const pollEvalStatus = async () => {
    try {
      const resp = await axios.get('/api/prompts/eval/status')
      const status: EvalStatus = resp.data
      setEvalStatus(status.prompt_id ? status : null)
      if (status.is_running && !evalPollRef.current) {
        evalPollRef.current = setInterval(pollEvalStatus, 2500)
      } else if (!status.is_running && evalPollRef.current) {
        clearInterval(evalPollRef.current)
        evalPollRef.current = null
      }
    } catch (e) {
      console.error('Error polling eval status', e)
    }
  }

  const startEval = async (p: PromptDef) => {
    try {
      await axios.post(`/api/prompts/${p.id}/eval`, { template: drafts[p.id] || '', sample_size: 5 })
      showNotification('Evaluation started — reprocessing verified snapshots with the candidate prompt.', 'success')
      await pollEvalStatus()
      if (!evalPollRef.current) evalPollRef.current = setInterval(pollEvalStatus, 2500)
    } catch (e: any) {
      showNotification(e.response?.data?.detail || 'Failed to start evaluation.', 'danger')
    }
  }

  const applyPrompts = (list: PromptDef[]) => {
    setPrompts(list)
    const d: Record<string, string> = {}
    list.forEach((p) => {
      d[p.id] = p.template
    })
    setDrafts(d)
  }

  const loadPrompts = async () => {
    try {
      setLoading(true)
      const resp = await axios.get('/api/prompts')
      applyPrompts(resp.data.prompts || [])
    } catch (e) {
      console.error('Error loading prompts', e)
      showNotification('Failed to load pipeline prompts.', 'danger')
    } finally {
      setLoading(false)
    }
  }

  const savePrompt = async (p: PromptDef) => {
    try {
      setSavingId(p.id)
      const resp = await axios.post(`/api/prompts/${p.id}`, { template: drafts[p.id] || '' })
      applyPrompts(resp.data.prompts || [])
      showNotification(`Prompt "${p.label}" saved.`, 'success')
    } catch (e: any) {
      showNotification(e.response?.data?.detail || 'Failed to save prompt.', 'danger')
    } finally {
      setSavingId(null)
    }
  }

  const resetPrompt = async (p: PromptDef) => {
    if (!window.confirm(`Reset "${p.label}" to the built-in default template?`)) return
    try {
      setSavingId(p.id)
      const resp = await axios.post(`/api/prompts/${p.id}/reset`)
      applyPrompts(resp.data.prompts || [])
      showNotification(`Prompt "${p.label}" reset to default.`, 'success')
    } catch (e: any) {
      showNotification(e.response?.data?.detail || 'Failed to reset prompt.', 'danger')
    } finally {
      setSavingId(null)
    }
  }

  const groups = prompts.reduce((acc: Record<string, PromptDef[]>, p) => {
    acc[p.group] = acc[p.group] || []
    acc[p.group].push(p)
    return acc
  }, {})

  return (
    <div className="bg-surface-container-lowest border border-surface-container-high p-6 rounded-lg space-y-5">
      <div className="border-b border-surface-container-high pb-3">
        <h3 className="font-bold text-headline-sm text-neutral-dark flex items-center gap-2">
          <FileTerminal className="w-5 h-5 text-primary" /> Pipeline Prompts
        </h3>
      </div>

      <p className="text-text-secondary text-body-sm leading-relaxed">
        Customize the exact instructions each pipeline model receives. Placeholders in{' '}
        <code className="font-mono text-technical-sm bg-surface-container-low border border-surface-container-high px-1 rounded">
          {'{braces}'}
        </code>{' '}
        are substituted at runtime (removing one disables that context block); all other braces — such as the JSON
        response schema — are passed through literally. Customized prompts survive updates and can be reset to the
        built-in default at any time.
      </p>

      {loading ? (
        <div className="h-24 flex items-center justify-center text-text-secondary">
          <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading prompts...
        </div>
      ) : (
        Object.entries(groups).map(([group, groupPrompts]) => (
          <div key={group} className="space-y-3">
            <span className="text-[10px] font-bold uppercase tracking-wider text-text-secondary font-mono">{group}</span>
            {groupPrompts.map((p) => {
              const isExpanded = expandedId === p.id
              const isDirty = (drafts[p.id] || '') !== p.template
              return (
                <div key={p.id} className="rounded border border-surface-container-high bg-surface-container-low">
                  <button
                    type="button"
                    onClick={() => setExpandedId(isExpanded ? null : p.id)}
                    className="w-full text-left p-4 flex items-start justify-between gap-3 cursor-pointer select-none"
                  >
                    <div className="min-w-0 space-y-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-bold text-neutral-dark text-body-md">{p.label}</span>
                        {p.is_customized && (
                          <span className="text-[10px] font-semibold uppercase tracking-wider font-mono px-2 py-0.5 rounded border border-primary/20 bg-accent-surface text-primary flex items-center gap-1">
                            <BadgeCheck className="w-3 h-3" /> Customized
                          </span>
                        )}
                      </div>
                      <p className="text-text-secondary text-body-sm leading-relaxed">{p.description}</p>
                    </div>
                    {isExpanded ? (
                      <ChevronDown className="w-4 h-4 shrink-0 mt-1 text-text-secondary" />
                    ) : (
                      <ChevronRight className="w-4 h-4 shrink-0 mt-1 text-text-secondary" />
                    )}
                  </button>

                  {isExpanded && (
                    <div className="px-4 pb-4 space-y-3">
                      {p.placeholders.length > 0 && (
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <Braces className="w-3.5 h-3.5 text-text-secondary" />
                          {p.placeholders.map((ph) => (
                            <button
                              key={ph}
                              type="button"
                              title="Insert placeholder at end"
                              onClick={() => setDrafts({ ...drafts, [p.id]: `${drafts[p.id] || ''}{${ph}}` })}
                              className="text-[10px] font-mono px-2 py-0.5 rounded bg-surface-container-lowest border border-surface-container-high text-neutral-dark cursor-pointer hover:border-primary"
                            >
                              {'{' + ph + '}'}
                            </button>
                          ))}
                        </div>
                      )}
                      <textarea
                        value={drafts[p.id] || ''}
                        onChange={(e) => setDrafts({ ...drafts, [p.id]: e.target.value })}
                        rows={16}
                        spellCheck={false}
                        className="w-full bg-surface-container-lowest border border-surface-container-high p-3 rounded text-technical-sm font-mono text-neutral-dark outline-none focus:border-primary leading-normal"
                      />
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            onClick={() => resetPrompt(p)}
                            disabled={savingId === p.id || (!p.is_customized && !isDirty)}
                            className="bg-surface-container-lowest hover:bg-surface-container border border-surface-container-high text-neutral-dark font-bold h-9 px-3 rounded flex items-center gap-2 cursor-pointer disabled:opacity-40 text-action-sm"
                          >
                            <RotateCcw className="w-3.5 h-3.5" /> Reset to Default
                          </button>
                          {EVALUABLE.includes(p.id) && (
                            <button
                              type="button"
                              title="Reprocess a sample of human-verified snapshots with THIS template (nothing is persisted) and score agreement with your labels"
                              onClick={() => startEval(p)}
                              disabled={evalStatus?.is_running || false}
                              className="bg-accent-surface hover:bg-surface-container text-primary font-bold h-9 px-3 rounded border border-primary/20 flex items-center gap-2 cursor-pointer disabled:opacity-40 text-action-sm"
                            >
                              {evalStatus?.is_running && evalStatus.prompt_id === p.id ? (
                                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                              ) : (
                                <FlaskConical className="w-3.5 h-3.5" />
                              )}
                              Evaluate on Verified Labels
                            </button>
                          )}
                        </div>
                        <button
                          type="button"
                          onClick={() => savePrompt(p)}
                          disabled={savingId === p.id || !isDirty}
                          className="bg-primary hover:opacity-90 text-on-primary font-bold h-9 px-4 rounded flex items-center gap-2 cursor-pointer disabled:opacity-40 text-action-sm"
                        >
                          {savingId === p.id ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : (
                            <CheckCircle2 className="w-3.5 h-3.5" />
                          )}
                          Save Prompt
                        </button>
                      </div>

                      {/* Evaluation progress & per-record agreement */}
                      {evalStatus && evalStatus.prompt_id === p.id && (
                        <div className="p-3 rounded border border-surface-container-high bg-surface-container-lowest space-y-2">
                          <div className="flex items-center justify-between text-[10px] font-semibold uppercase tracking-wider text-text-secondary font-messina">
                            <span className="flex items-center gap-1.5">
                              <FlaskConical className="w-3.5 h-3.5 text-primary" />
                              {evalStatus.is_running
                                ? `Evaluating ${evalStatus.completed}/${evalStatus.total}...`
                                : `Evaluation complete — ${evalStatus.completed}/${evalStatus.total} snapshots`}
                            </span>
                            {evalStatus.accuracy !== null && (
                              <span className="font-mono text-primary normal-case">
                                Label agreement: {(evalStatus.accuracy * 100).toFixed(0)}%
                              </span>
                            )}
                          </div>
                          {evalStatus.error && (
                            <p className="text-body-sm text-danger-primary flex items-center gap-1.5">
                              <AlertCircle className="w-4 h-4" /> {evalStatus.error}
                            </p>
                          )}
                          <div className="space-y-1 max-h-48 overflow-y-auto">
                            {evalStatus.results.map((r) => (
                              <div
                                key={r.id}
                                className="flex items-center gap-2 text-technical-sm font-mono text-neutral-dark"
                              >
                                {r.error ? (
                                  <AlertCircle className="w-3.5 h-3.5 text-danger-primary shrink-0" />
                                ) : r.match ? (
                                  <Check className="w-3.5 h-3.5 text-success-green shrink-0" />
                                ) : (
                                  <X className="w-3.5 h-3.5 text-danger-primary shrink-0" />
                                )}
                                <span className="truncate flex-1" title={r.window_title}>
                                  {r.app_name} · {r.window_title}
                                </span>
                                <span className="text-text-secondary shrink-0">
                                  {r.error
                                    ? 'error'
                                    : `${r.predicted_project || 'None'} vs ${r.human_project || 'None'}`}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        ))
      )}
    </div>
  )
}
