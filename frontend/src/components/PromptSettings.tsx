import React, { useState, useEffect } from 'react'
import axios from 'axios'
import {
  FileTerminal,
  Loader2,
  CheckCircle2,
  RotateCcw,
  ChevronDown,
  ChevronRight,
  Braces,
  BadgeCheck
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

export const PromptSettings: React.FC<PromptSettingsProps> = ({ showNotification }) => {
  const [prompts, setPrompts] = useState<PromptDef[]>([])
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState<boolean>(true)
  const [savingId, setSavingId] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  useEffect(() => {
    loadPrompts()
  }, [])

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
                        <button
                          type="button"
                          onClick={() => resetPrompt(p)}
                          disabled={savingId === p.id || (!p.is_customized && !isDirty)}
                          className="bg-surface-container-lowest hover:bg-surface-container border border-surface-container-high text-neutral-dark font-bold h-9 px-3 rounded flex items-center gap-2 cursor-pointer disabled:opacity-40 text-action-sm"
                        >
                          <RotateCcw className="w-3.5 h-3.5" /> Reset to Default
                        </button>
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
