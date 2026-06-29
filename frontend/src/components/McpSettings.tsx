import React, { useState, useEffect } from 'react'
import axios from 'axios'
import {
  Plug,
  Plus,
  Trash2,
  Pencil,
  Activity,
  Loader2,
  CheckCircle2,
  AlertCircle,
  Server,
  Globe,
  Lock,
  X,
  Power,
  Wrench
} from 'lucide-react'

interface McpSettingsProps {
  showNotification: (text: string, type: 'success' | 'danger') => void
}

interface Slot {
  id: string
  label: string
  group: string
}

interface McpServer {
  id?: string
  name: string
  enabled: boolean
  transport: 'stdio' | 'http' | 'sse'
  command?: string
  args?: string[]
  env?: Record<string, string>
  cwd?: string
  url?: string
  auth_type?: 'none' | 'bearer' | 'header'
  auth_token?: string
  header_name?: string
  assignments?: string[]
}

interface DiscoveredTool {
  name: string
  description: string
  input_schema: any
}

const SECRET_MASK = '••••••••'

const blankServer = (): McpServer => ({
  name: '',
  enabled: true,
  transport: 'stdio',
  command: '',
  args: [],
  env: {},
  cwd: '',
  url: '',
  auth_type: 'none',
  auth_token: '',
  header_name: 'Authorization',
  assignments: []
})

const PRESETS: Record<string, Partial<McpServer>> = {
  github_remote: {
    name: 'GitHub (Remote)',
    transport: 'http',
    url: 'https://api.githubcopilot.com/mcp/',
    auth_type: 'bearer',
    auth_token: ''
  },
  github_local: {
    name: 'GitHub (Local)',
    transport: 'stdio',
    command: 'docker',
    args: ['run', '-i', '--rm', '-e', 'GITHUB_PERSONAL_ACCESS_TOKEN', 'ghcr.io/github/github-mcp-server'],
    env: { GITHUB_PERSONAL_ACCESS_TOKEN: '' },
    auth_type: 'none'
  },
  atlassian_remote: {
    name: 'Atlassian (Remote)',
    transport: 'sse',
    url: 'https://mcp.atlassian.com/v1/sse',
    auth_type: 'bearer',
    auth_token: ''
  }
}

export const McpSettings: React.FC<McpSettingsProps> = ({ showNotification }) => {
  const [slots, setSlots] = useState<Slot[]>([])
  const [servers, setServers] = useState<McpServer[]>([])
  const [loading, setLoading] = useState<boolean>(true)
  const [editing, setEditing] = useState<McpServer | null>(null)
  const [saving, setSaving] = useState<boolean>(false)
  const [testing, setTesting] = useState<boolean>(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; error?: string; tools?: DiscoveredTool[] } | null>(null)

  useEffect(() => {
    loadAll()
  }, [])

  const loadAll = async () => {
    try {
      setLoading(true)
      const [slotsResp, serversResp] = await Promise.all([
        axios.get('/api/mcp/slots'),
        axios.get('/api/mcp/servers')
      ])
      setSlots(slotsResp.data.slots || [])
      setServers(serversResp.data.servers || [])
    } catch (e) {
      console.error('Error loading MCP config', e)
      showNotification('Failed to load MCP server configuration.', 'danger')
    } finally {
      setLoading(false)
    }
  }

  const startAdd = () => {
    setTestResult(null)
    setEditing(blankServer())
  }

  const startEdit = (srv: McpServer) => {
    setTestResult(null)
    setEditing({ ...blankServer(), ...srv })
  }

  const applyPreset = (key: string) => {
    if (!editing || !key) return
    setEditing({ ...editing, ...PRESETS[key] } as McpServer)
  }

  const setField = (field: keyof McpServer, value: any) => {
    if (!editing) return
    setEditing({ ...editing, [field]: value })
  }

  const toggleAssignment = (slotId: string) => {
    if (!editing) return
    const current = editing.assignments || []
    const next = current.includes(slotId) ? current.filter((a) => a !== slotId) : [...current, slotId]
    setEditing({ ...editing, assignments: next })
  }

  const saveServer = async () => {
    if (!editing) return
    if (!editing.name.trim()) {
      showNotification('Please give the MCP server a name.', 'danger')
      return
    }
    try {
      setSaving(true)
      const resp = await axios.post('/api/mcp/servers', editing)
      showNotification(`MCP server "${editing.name}" saved.`, 'success')
      setEditing(null)
      setTestResult(null)
      // Refresh list
      setServers((prev) => {
        const saved = resp.data.server
        const exists = prev.some((s) => s.id === saved.id)
        return exists ? prev.map((s) => (s.id === saved.id ? saved : s)) : [...prev, saved]
      })
    } catch (e: any) {
      showNotification(e.response?.data?.detail || 'Failed to save MCP server.', 'danger')
    } finally {
      setSaving(false)
    }
  }

  const deleteServer = async (srv: McpServer) => {
    if (!srv.id) return
    if (!window.confirm(`Delete MCP server "${srv.name}"? This cannot be undone.`)) return
    try {
      await axios.delete(`/api/mcp/servers/${srv.id}`)
      setServers((prev) => prev.filter((s) => s.id !== srv.id))
      showNotification(`Deleted "${srv.name}".`, 'success')
    } catch (e: any) {
      showNotification(e.response?.data?.detail || 'Failed to delete MCP server.', 'danger')
    }
  }

  const toggleEnabled = async (srv: McpServer) => {
    try {
      const updated = { ...srv, enabled: !srv.enabled }
      const resp = await axios.post('/api/mcp/servers', updated)
      setServers((prev) => prev.map((s) => (s.id === srv.id ? resp.data.server : s)))
    } catch (e: any) {
      showNotification('Failed to toggle server state.', 'danger')
    }
  }

  const testConnection = async () => {
    if (!editing) return
    try {
      setTesting(true)
      setTestResult(null)
      const resp = await axios.post('/api/mcp/servers/test', { server: editing })
      setTestResult(resp.data)
      if (resp.data.ok) {
        showNotification(`Connected — discovered ${resp.data.tool_count} tool(s).`, 'success')
      } else {
        showNotification('MCP connection failed.', 'danger')
      }
    } catch (e: any) {
      const msg = e.response?.data?.detail || e.message || 'Connection error.'
      setTestResult({ ok: false, error: msg })
      showNotification('MCP connection failed.', 'danger')
    } finally {
      setTesting(false)
    }
  }

  const slotLabel = (id: string) => slots.find((s) => s.id === id)?.label || id
  const isRemote = editing && editing.transport !== 'stdio'

  const groupedSlots = slots.reduce((acc: Record<string, Slot[]>, s) => {
    acc[s.group] = acc[s.group] || []
    acc[s.group].push(s)
    return acc
  }, {})

  return (
    <div className="bg-surface-container-lowest border border-surface-container-high p-6 rounded-lg space-y-5">
      <div className="flex items-center justify-between border-b border-surface-container-high pb-3">
        <h3 className="font-bold text-headline-sm text-neutral-dark flex items-center gap-2">
          <Plug className="w-5 h-5 text-primary" /> MCP Integrations
        </h3>
        <button
          type="button"
          onClick={startAdd}
          className="bg-primary hover:opacity-90 text-on-primary text-action-md font-bold h-9 px-4 rounded flex items-center gap-2 cursor-pointer"
        >
          <Plus className="w-4 h-4" /> Add Server
        </button>
      </div>

      <p className="text-text-secondary text-body-sm leading-relaxed">
        Connect local or remote Model Context Protocol servers (GitHub, Atlassian, and more) and assign each one to
        individual pipeline prompts and/or the Ask Memory Agent for fine-grained control over where external tools are used.
      </p>

      {loading ? (
        <div className="h-24 flex items-center justify-center text-text-secondary">
          <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading MCP servers...
        </div>
      ) : (
        <>
          {/* Server list */}
          {servers.length === 0 && !editing ? (
            <div className="p-6 rounded border border-dashed border-surface-container-high text-center text-text-secondary text-body-sm">
              No MCP servers configured yet. Click <strong>Add Server</strong> to connect GitHub or Atlassian.
            </div>
          ) : (
            <div className="space-y-3">
              {servers.map((srv) => (
                <div
                  key={srv.id}
                  className={`p-4 rounded border ${
                    srv.enabled ? 'border-surface-container-high bg-surface-container-low' : 'border-surface-container-high bg-surface-container-low/40 opacity-60'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="space-y-1.5 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-bold text-neutral-dark text-body-md truncate">{srv.name}</span>
                        <span className="text-[10px] font-semibold uppercase tracking-wider font-mono px-2 py-0.5 rounded border border-surface-container-high bg-surface-container-lowest text-text-secondary flex items-center gap-1">
                          {srv.transport === 'stdio' ? <Server className="w-3 h-3" /> : <Globe className="w-3 h-3" />}
                          {srv.transport}
                        </span>
                        {srv.auth_type && srv.auth_type !== 'none' && (
                          <span className="text-[10px] font-semibold uppercase tracking-wider font-mono px-2 py-0.5 rounded border border-primary/20 bg-accent-surface text-primary flex items-center gap-1">
                            <Lock className="w-3 h-3" /> {srv.auth_type}
                          </span>
                        )}
                      </div>
                      <p className="text-technical-sm font-mono text-text-secondary truncate">
                        {srv.transport === 'stdio' ? `${srv.command} ${(srv.args || []).join(' ')}` : srv.url}
                      </p>
                      <div className="flex items-center gap-1.5 flex-wrap pt-1">
                        {(srv.assignments || []).length === 0 ? (
                          <span className="text-[11px] text-text-secondary italic">Not assigned to any prompt</span>
                        ) : (
                          (srv.assignments || []).map((a) => (
                            <span
                              key={a}
                              className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-accent-surface text-primary border border-primary/10"
                            >
                              {slotLabel(a)}
                            </span>
                          ))
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <button
                        type="button"
                        title={srv.enabled ? 'Disable' : 'Enable'}
                        onClick={() => toggleEnabled(srv)}
                        className={`w-8 h-8 rounded border flex items-center justify-center cursor-pointer transition-colors ${
                          srv.enabled
                            ? 'border-success-green/30 text-success-green bg-success-green/10'
                            : 'border-surface-container-high text-text-secondary bg-surface-container-lowest'
                        }`}
                      >
                        <Power className="w-4 h-4" />
                      </button>
                      <button
                        type="button"
                        title="Edit"
                        onClick={() => startEdit(srv)}
                        className="w-8 h-8 rounded border border-surface-container-high text-neutral-dark bg-surface-container-lowest flex items-center justify-center cursor-pointer hover:border-primary"
                      >
                        <Pencil className="w-4 h-4" />
                      </button>
                      <button
                        type="button"
                        title="Delete"
                        onClick={() => deleteServer(srv)}
                        className="w-8 h-8 rounded border border-danger-primary/30 text-danger-primary bg-danger-surface/30 flex items-center justify-center cursor-pointer hover:bg-danger-surface"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Editor */}
          {editing && (
            <div className="mt-4 p-5 rounded-lg border-2 border-primary/30 bg-accent-surface/10 space-y-4">
              <div className="flex items-center justify-between">
                <h4 className="font-bold text-body-md text-neutral-dark">
                  {editing.id ? 'Edit MCP Server' : 'New MCP Server'}
                </h4>
                <button
                  type="button"
                  onClick={() => {
                    setEditing(null)
                    setTestResult(null)
                  }}
                  className="text-text-secondary hover:text-neutral-dark cursor-pointer"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* Preset + name + transport */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <div className="space-y-1">
                  <label className="text-body-sm font-semibold text-text-secondary">Quick Preset</label>
                  <select
                    onChange={(e) => applyPreset(e.target.value)}
                    defaultValue=""
                    className="w-full bg-surface-container-low border border-surface-container-high h-10 px-3 rounded text-body-md text-neutral-dark outline-none focus:border-primary cursor-pointer"
                  >
                    <option value="">— Choose —</option>
                    <option value="github_remote">GitHub (Remote)</option>
                    <option value="github_local">GitHub (Local / Docker)</option>
                    <option value="atlassian_remote">Atlassian (Remote)</option>
                  </select>
                </div>
                <div className="space-y-1">
                  <label className="text-body-sm font-semibold text-text-secondary">Display Name</label>
                  <input
                    type="text"
                    value={editing.name}
                    onChange={(e) => setField('name', e.target.value)}
                    placeholder="e.g. GitHub"
                    className="w-full bg-surface-container-low border border-surface-container-high h-10 px-3 rounded text-body-md text-neutral-dark outline-none focus:border-primary"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-body-sm font-semibold text-text-secondary">Transport</label>
                  <select
                    value={editing.transport}
                    onChange={(e) => setField('transport', e.target.value)}
                    className="w-full bg-surface-container-low border border-surface-container-high h-10 px-3 rounded text-body-md text-neutral-dark outline-none focus:border-primary cursor-pointer"
                  >
                    <option value="stdio">Local (stdio)</option>
                    <option value="http">Remote (Streamable HTTP)</option>
                    <option value="sse">Remote (SSE)</option>
                  </select>
                </div>
              </div>

              {/* Connection details */}
              {!isRemote ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div className="space-y-1">
                    <label className="text-body-sm font-semibold text-text-secondary">Command</label>
                    <input
                      type="text"
                      value={editing.command || ''}
                      onChange={(e) => setField('command', e.target.value)}
                      placeholder="e.g. docker, npx, uvx"
                      className="w-full bg-surface-container-low border border-surface-container-high h-10 px-3 rounded text-body-md text-neutral-dark outline-none focus:border-primary font-mono"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="text-body-sm font-semibold text-text-secondary">Arguments (space-separated)</label>
                    <input
                      type="text"
                      value={(editing.args || []).join(' ')}
                      onChange={(e) => setField('args', e.target.value.split(' ').filter((x) => x !== ''))}
                      placeholder="-y @modelcontextprotocol/server-github"
                      className="w-full bg-surface-container-low border border-surface-container-high h-10 px-3 rounded text-body-md text-neutral-dark outline-none focus:border-primary font-mono"
                    />
                  </div>
                  <div className="space-y-1 md:col-span-2">
                    <label className="text-body-sm font-semibold text-text-secondary">
                      Environment Variables (KEY=value, one per line)
                    </label>
                    <textarea
                      value={Object.entries(editing.env || {})
                        .map(([k, v]) => `${k}=${v}`)
                        .join('\n')}
                      onChange={(e) => {
                        const env: Record<string, string> = {}
                        e.target.value.split('\n').forEach((line) => {
                          const idx = line.indexOf('=')
                          if (idx > 0) env[line.slice(0, idx).trim()] = line.slice(idx + 1).trim()
                        })
                        setField('env', env)
                      }}
                      rows={3}
                      placeholder="GITHUB_PERSONAL_ACCESS_TOKEN=ghp_..."
                      className="w-full bg-surface-container-low border border-surface-container-high px-3 py-2 rounded text-body-sm text-neutral-dark outline-none focus:border-primary font-mono"
                    />
                  </div>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div className="space-y-1 md:col-span-2">
                    <label className="text-body-sm font-semibold text-text-secondary">Server URL</label>
                    <input
                      type="text"
                      value={editing.url || ''}
                      onChange={(e) => setField('url', e.target.value)}
                      placeholder="https://api.githubcopilot.com/mcp/"
                      className="w-full bg-surface-container-low border border-surface-container-high h-10 px-3 rounded text-body-md text-neutral-dark outline-none focus:border-primary font-mono"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="text-body-sm font-semibold text-text-secondary">Authentication</label>
                    <select
                      value={editing.auth_type || 'none'}
                      onChange={(e) => setField('auth_type', e.target.value)}
                      className="w-full bg-surface-container-low border border-surface-container-high h-10 px-3 rounded text-body-md text-neutral-dark outline-none focus:border-primary cursor-pointer"
                    >
                      <option value="none">None</option>
                      <option value="bearer">Bearer Token</option>
                      <option value="header">Custom Header</option>
                    </select>
                  </div>
                  {editing.auth_type === 'header' && (
                    <div className="space-y-1">
                      <label className="text-body-sm font-semibold text-text-secondary">Header Name</label>
                      <input
                        type="text"
                        value={editing.header_name || ''}
                        onChange={(e) => setField('header_name', e.target.value)}
                        placeholder="X-Api-Key"
                        className="w-full bg-surface-container-low border border-surface-container-high h-10 px-3 rounded text-body-md text-neutral-dark outline-none focus:border-primary font-mono"
                      />
                    </div>
                  )}
                  {editing.auth_type && editing.auth_type !== 'none' && (
                    <div className="space-y-1 md:col-span-2">
                      <label className="text-body-sm font-semibold text-text-secondary flex items-center gap-1">
                        <Lock className="w-3 h-3" /> Token / Secret (AES-256 encrypted at rest)
                      </label>
                      <input
                        type="password"
                        value={editing.auth_token || ''}
                        onChange={(e) => setField('auth_token', e.target.value)}
                        placeholder={editing.auth_token === SECRET_MASK ? SECRET_MASK : 'Paste token...'}
                        className="w-full bg-surface-container-low border border-surface-container-high h-10 px-3 rounded text-body-md text-neutral-dark outline-none focus:border-primary font-mono"
                      />
                    </div>
                  )}
                </div>
              )}

              {/* Assignment matrix */}
              <div className="space-y-2 pt-1">
                <label className="text-body-sm font-semibold text-text-secondary">
                  Assign to prompts (where this server's tools may be used)
                </label>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  {Object.entries(groupedSlots).map(([group, groupSlots]) => (
                    <div key={group} className="p-3 rounded border border-surface-container-high bg-surface-container-lowest space-y-2">
                      <span className="text-[10px] font-bold uppercase tracking-wider text-text-secondary font-mono">
                        {group}
                      </span>
                      {groupSlots.map((s) => (
                        <label key={s.id} className="flex items-center gap-2 cursor-pointer text-body-sm text-neutral-dark">
                          <input
                            type="checkbox"
                            checked={(editing.assignments || []).includes(s.id)}
                            onChange={() => toggleAssignment(s.id)}
                            className="w-4 h-4 rounded border-surface-container-high text-primary"
                          />
                          {s.label}
                        </label>
                      ))}
                    </div>
                  ))}
                </div>
              </div>

              {/* Test result */}
              {testResult && (
                <div
                  className={`p-3 rounded border text-body-sm flex items-start gap-2 ${
                    testResult.ok
                      ? 'bg-success-green/10 border-success-green/20 text-success-green'
                      : 'bg-error-container/30 border-error-container text-error'
                  }`}
                >
                  {testResult.ok ? (
                    <CheckCircle2 className="w-5 h-5 shrink-0 mt-0.5" />
                  ) : (
                    <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
                  )}
                  <div className="min-w-0">
                    {testResult.ok ? (
                      <>
                        <strong className="block">Discovered {testResult.tools?.length || 0} tool(s)</strong>
                        <div className="flex flex-wrap gap-1.5 mt-1.5">
                          {(testResult.tools || []).map((t) => (
                            <span
                              key={t.name}
                              title={t.description}
                              className="text-[10px] font-mono px-2 py-0.5 rounded bg-surface-container-lowest border border-surface-container-high text-neutral-dark flex items-center gap-1"
                            >
                              <Wrench className="w-2.5 h-2.5" /> {t.name}
                            </span>
                          ))}
                        </div>
                      </>
                    ) : (
                      <>
                        <strong className="block">Connection failed</strong>
                        <span className="font-mono text-technical-sm break-all">{testResult.error}</span>
                      </>
                    )}
                  </div>
                </div>
              )}

              {/* Editor actions */}
              <div className="flex items-center justify-between pt-1">
                <button
                  type="button"
                  onClick={testConnection}
                  disabled={testing}
                  className="bg-accent-surface hover:bg-surface-container text-primary font-bold h-10 px-4 rounded border border-primary/20 flex items-center gap-2 cursor-pointer disabled:opacity-50"
                >
                  {testing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Activity className="w-4 h-4" />}
                  Test Connection
                </button>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setEditing(null)
                      setTestResult(null)
                    }}
                    className="bg-surface-container-low hover:bg-surface-container border border-surface-container-high text-neutral-dark font-bold h-10 px-4 rounded cursor-pointer"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={saveServer}
                    disabled={saving}
                    className="bg-primary hover:opacity-90 text-on-primary font-bold h-10 px-5 rounded flex items-center gap-2 cursor-pointer disabled:opacity-50"
                  >
                    {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
                    Save Server
                  </button>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
