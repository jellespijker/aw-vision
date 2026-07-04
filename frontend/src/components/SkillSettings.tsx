import React, { useState, useEffect, useRef } from 'react'
import axios from 'axios'
import {
  GraduationCap,
  Upload,
  Trash2,
  Loader2,
  Power,
  FileText,
  ChevronDown,
  ChevronRight,
  RefreshCw,
  FolderOpen
} from 'lucide-react'

interface SkillSettingsProps {
  showNotification: (text: string, type: 'success' | 'danger') => void
}

interface Slot {
  id: string
  label: string
  group: string
}

interface Skill {
  id: string
  name: string
  description: string
  enabled: boolean
  content: string
  filename: string
  assignments: string[]
  updated_at: number
  source?: 'upload' | 'disk'
}

const fileToBase64 = (file: File): Promise<string> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result as string
      // Strip the data-URL prefix ("data:...;base64,")
      resolve(result.slice(result.indexOf(',') + 1))
    }
    reader.onerror = reject
    reader.readAsDataURL(file)
  })

export const SkillSettings: React.FC<SkillSettingsProps> = ({ showNotification }) => {
  const [slots, setSlots] = useState<Slot[]>([])
  const [skills, setSkills] = useState<Skill[]>([])
  const [loading, setLoading] = useState<boolean>(true)
  const [uploading, setUploading] = useState<boolean>(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const replaceTargetRef = useRef<string | null>(null)

  useEffect(() => {
    loadAll()
  }, [])

  const loadAll = async () => {
    try {
      setLoading(true)
      const [slotsResp, skillsResp] = await Promise.all([axios.get('/api/mcp/slots'), axios.get('/api/skills')])
      setSlots(slotsResp.data.slots || [])
      setSkills(skillsResp.data.skills || [])
    } catch (e) {
      console.error('Error loading skills', e)
      showNotification('Failed to load Claude Skills.', 'danger')
    } finally {
      setLoading(false)
    }
  }

  const startUpload = (skillId: string | null = null) => {
    replaceTargetRef.current = skillId
    fileInputRef.current?.click()
  }

  const handleFileChosen = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = '' // Allow re-selecting the same file later
    if (!file) return
    try {
      setUploading(true)
      const content_base64 = await fileToBase64(file)
      const resp = await axios.post('/api/skills/upload', {
        filename: file.name,
        content_base64,
        skill_id: replaceTargetRef.current
      })
      const saved: Skill = resp.data.skill
      setSkills((prev) => {
        const exists = prev.some((s) => s.id === saved.id)
        return exists ? prev.map((s) => (s.id === saved.id ? saved : s)) : [...prev, saved]
      })
      showNotification(`Skill "${saved.name}" uploaded.`, 'success')
    } catch (err: any) {
      showNotification(err.response?.data?.detail || 'Failed to upload skill file.', 'danger')
    } finally {
      setUploading(false)
      replaceTargetRef.current = null
    }
  }

  const persistSkill = async (updated: Skill) => {
    try {
      // Send metadata only; the backend keeps the stored content when content is omitted.
      const { content, ...meta } = updated
      const resp = await axios.post('/api/skills', meta)
      setSkills((prev) => prev.map((s) => (s.id === updated.id ? { ...resp.data.skill, content: content ?? resp.data.skill.content } : s)))
    } catch (err: any) {
      showNotification(err.response?.data?.detail || 'Failed to update skill.', 'danger')
    }
  }

  const toggleEnabled = (skill: Skill) => persistSkill({ ...skill, enabled: !skill.enabled })

  const toggleAssignment = (skill: Skill, slotId: string) => {
    const current = skill.assignments || []
    const next = current.includes(slotId) ? current.filter((a) => a !== slotId) : [...current, slotId]
    persistSkill({ ...skill, assignments: next })
  }

  const deleteSkill = async (skill: Skill) => {
    if (!window.confirm(`Delete skill "${skill.name}"? This cannot be undone.`)) return
    try {
      await axios.delete(`/api/skills/${skill.id}`)
      setSkills((prev) => prev.filter((s) => s.id !== skill.id))
      showNotification(`Deleted "${skill.name}".`, 'success')
    } catch (err: any) {
      showNotification(err.response?.data?.detail || 'Failed to delete skill.', 'danger')
    }
  }

  const groupedSlots = slots.reduce((acc: Record<string, Slot[]>, s) => {
    acc[s.group] = acc[s.group] || []
    acc[s.group].push(s)
    return acc
  }, {})

  return (
    <div className="bg-surface-container-lowest border border-surface-container-high p-6 rounded-lg space-y-5">
      <input
        ref={fileInputRef}
        type="file"
        accept=".md,.markdown,.txt,.zip"
        onChange={handleFileChosen}
        className="hidden"
      />

      <div className="flex items-center justify-between border-b border-surface-container-high pb-3">
        <h3 className="font-bold text-headline-sm text-neutral-dark flex items-center gap-2">
          <GraduationCap className="w-5 h-5 text-primary" /> Claude Skills
        </h3>
        <button
          type="button"
          onClick={() => startUpload(null)}
          disabled={uploading}
          className="bg-primary hover:opacity-90 text-on-primary text-action-md font-bold h-9 px-4 rounded flex items-center gap-2 cursor-pointer disabled:opacity-50"
        >
          {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />} Upload Skill
        </button>
      </div>

      <p className="text-text-secondary text-body-sm leading-relaxed">
        Upload Claude Skills (a <code className="font-mono text-technical-sm">SKILL.md</code> file or a{' '}
        <code className="font-mono text-technical-sm">.zip</code> bundle containing one) and assign each skill to
        individual pipeline prompts and/or the Ask Memory Agent — exactly like MCP servers. Assigned skills inject
        their expert instructions into that prompt, steering context extraction and project classification. Skills
        placed in the configured skills directory (<code className="font-mono text-technical-sm">config.toml →
        customization.skills_dir</code>) are discovered automatically on startup; their content is managed on disk
        while assignments and the enabled toggle are managed here.
      </p>

      {loading ? (
        <div className="h-24 flex items-center justify-center text-text-secondary">
          <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading skills...
        </div>
      ) : skills.length === 0 ? (
        <div className="p-6 rounded border border-dashed border-surface-container-high text-center text-text-secondary text-body-sm">
          No skills uploaded yet. Click <strong>Upload Skill</strong> to add a SKILL.md file.
        </div>
      ) : (
        <div className="space-y-3">
          {skills.map((skill) => {
            const isExpanded = expandedId === skill.id
            return (
              <div
                key={skill.id}
                className={`p-4 rounded border border-surface-container-high ${
                  skill.enabled ? 'bg-surface-container-low' : 'bg-surface-container-low/40 opacity-60'
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="space-y-1.5 min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-bold text-neutral-dark text-body-md truncate">{skill.name}</span>
                      {skill.filename && (
                        <span className="text-[10px] font-semibold font-mono px-2 py-0.5 rounded border border-surface-container-high bg-surface-container-lowest text-text-secondary flex items-center gap-1">
                          <FileText className="w-3 h-3" /> {skill.filename}
                        </span>
                      )}
                      {skill.source === 'disk' && (
                        <span
                          title="Auto-discovered from the configured skills directory; content is managed on disk"
                          className="text-[10px] font-semibold uppercase tracking-wider font-mono px-2 py-0.5 rounded border border-primary/20 bg-accent-surface text-primary flex items-center gap-1"
                        >
                          <FolderOpen className="w-3 h-3" /> Disk
                        </span>
                      )}
                    </div>
                    {skill.description && (
                      <p className="text-body-sm text-text-secondary leading-relaxed">{skill.description}</p>
                    )}

                    {/* Assignment matrix */}
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-2">
                      {Object.entries(groupedSlots).map(([group, groupSlots]) => (
                        <div
                          key={group}
                          className="p-3 rounded border border-surface-container-high bg-surface-container-lowest space-y-2"
                        >
                          <span className="text-[10px] font-bold uppercase tracking-wider text-text-secondary font-mono">
                            {group}
                          </span>
                          {groupSlots.map((s) => (
                            <label
                              key={s.id}
                              className="flex items-center gap-2 cursor-pointer text-body-sm text-neutral-dark"
                            >
                              <input
                                type="checkbox"
                                checked={(skill.assignments || []).includes(s.id)}
                                onChange={() => toggleAssignment(skill, s.id)}
                                className="w-4 h-4 rounded border-surface-container-high text-primary"
                              />
                              {s.label}
                            </label>
                          ))}
                        </div>
                      ))}
                    </div>

                    {/* Collapsible content preview */}
                    <button
                      type="button"
                      onClick={() => setExpandedId(isExpanded ? null : skill.id)}
                      className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-text-secondary font-messina cursor-pointer select-none pt-2"
                    >
                      {isExpanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                      {isExpanded ? 'Hide Skill Instructions' : 'View Skill Instructions'}
                    </button>
                    {isExpanded && (
                      <pre className="text-technical-sm font-mono text-neutral-dark whitespace-pre-wrap max-h-64 overflow-y-auto border border-surface-container p-3 rounded bg-surface-container-lowest leading-normal">
                        {skill.content}
                      </pre>
                    )}
                  </div>

                  <div className="flex items-center gap-1.5 shrink-0">
                    <button
                      type="button"
                      title={skill.enabled ? 'Disable' : 'Enable'}
                      onClick={() => toggleEnabled(skill)}
                      className={`w-8 h-8 rounded border flex items-center justify-center cursor-pointer transition-colors ${
                        skill.enabled
                          ? 'border-success-green/30 text-success-green bg-success-green/10'
                          : 'border-surface-container-high text-text-secondary bg-surface-container-lowest'
                      }`}
                    >
                      <Power className="w-4 h-4" />
                    </button>
                    {skill.source !== 'disk' && (
                      <>
                        <button
                          type="button"
                          title="Replace skill file"
                          onClick={() => startUpload(skill.id)}
                          className="w-8 h-8 rounded border border-surface-container-high text-neutral-dark bg-surface-container-lowest flex items-center justify-center cursor-pointer hover:border-primary"
                        >
                          <RefreshCw className="w-4 h-4" />
                        </button>
                        <button
                          type="button"
                          title="Delete"
                          onClick={() => deleteSkill(skill)}
                          className="w-8 h-8 rounded border border-danger-primary/30 text-danger-primary bg-danger-surface/30 flex items-center justify-center cursor-pointer hover:bg-danger-surface"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
