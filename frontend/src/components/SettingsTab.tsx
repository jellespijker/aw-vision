import React, { useState, useEffect, useRef } from 'react'
import axios from 'axios'
import {
  Settings,
  Key,
  Bot,
  Cpu,
  Server,
  Activity,
  Database,
  AlertCircle,
  CheckCircle2,
  Loader2,
  Lock,
  Eye,
  EyeOff,
  RefreshCw,
  Sparkles,
  ShieldAlert,
  Plug,
  Camera,
  Clock,
  FileTerminal,
  GraduationCap
} from 'lucide-react'
import { McpSettings } from './McpSettings'
import { PromptSettings } from './PromptSettings'
import { SkillSettings } from './SkillSettings'
import { CaptureSettings } from './CaptureSettings'

interface SettingsTabProps {
  showNotification: (text: string, type: 'success' | 'danger') => void
}

interface GeminiModel {
  id: string
  display_name: string
  description: string
}

interface ReembedStatus {
  is_running: boolean
  total_records: number
  processed_records: number
  error: string | null
  current_model: string
}

export const SettingsTab: React.FC<SettingsTabProps> = ({ showNotification }) => {
  // Settings state
  const [settings, setSettings] = useState<Record<string, any>>({
    provider: 'gemini',
    ocr_provider: 'ollama',
    gemini_api_key: '',
    gemini_llm_model: 'gemma-4-26b-a4b-it',
    gemini_embedding_model: 'gemini-embedding-002',
    gemini_context_size: 1048576,
    gemini_rate_limit_delay: 4.0,
    ollama_vision_model: 'gemma4:e2b-it-qat',
    ollama_ocr_model: 'glm-ocr:q8_0',
    ollama_embedding_model: 'embeddinggemma',
    ollama_context_size: 8192,
    agent_provider: 'ollama',
    agent_model: 'gemma4:e2b-it-qat',
    agent_context_size: 8192,
    max_ocr_chars: 1200,
    max_tool_result_chars: 3000,
    max_summarize_chunk_chars: 15000,
    screenshot_interval_seconds: 60,
    check_interval_seconds: 10,
    max_screenshot_lifetime_days: 14,
    cleanup_interval_hours: 1
  })

  const [loading, setLoading] = useState<boolean>(true)
  const [saving, setSaving] = useState<boolean>(false)
  const [showKey, setShowKey] = useState<boolean>(false)

  // Active settings sub-section (tab within the Settings page)
  type SettingsSection = 'provider' | 'models' | 'agent' | 'capture' | 'database' | 'mcp' | 'prompts' | 'skills'
  const [section, setSection] = useState<SettingsSection>('provider')

  // API testing states
  const [testingKey, setTestingKey] = useState<boolean>(false)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)

  // Model lists
  const [geminiModels, setGeminiModels] = useState<GeminiModel[]>([])
  const [fetchingModels, setFetchingModels] = useState<boolean>(false)

  // Re-embedding migration status
  const [reembedStatus, setReembedStatus] = useState<ReembedStatus>({
    is_running: false,
    total_records: 0,
    processed_records: 0,
    error: null,
    current_model: ''
  })

  const pollingRef = useRef<any>(null)

  // Load initial settings and re-embedding status
  useEffect(() => {
    fetchSettings()
    fetchReembedStatus()
    // Poll re-embedding status every 4 seconds
    pollingRef.current = setInterval(fetchReembedStatus, 4000)
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
    }
  }, [])

  // Poll more aggressively if re-embedding migration is active
  useEffect(() => {
    if (reembedStatus.is_running) {
      if (pollingRef.current) clearInterval(pollingRef.current)
      pollingRef.current = setInterval(fetchReembedStatus, 1500)
    } else {
      if (pollingRef.current) clearInterval(pollingRef.current)
      pollingRef.current = setInterval(fetchReembedStatus, 5000)
    }
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
    }
  }, [reembedStatus.is_running])

  // Retrieve Gemini models when the API key or provider changes
  useEffect(() => {
    if (settings.gemini_api_key && settings.gemini_api_key !== '••••••••') {
      fetchGeminiModels(settings.gemini_api_key)
    } else if (settings.gemini_api_key === '••••••••') {
      fetchGeminiModels()
    }
  }, [settings.gemini_api_key])

  const fetchSettings = async () => {
    try {
      setLoading(true)
      const resp = await axios.get('/api/settings')
      setSettings(resp.data)
    } catch (e) {
      console.error('Error fetching settings', e)
      showNotification('Failed to load system settings from backend.', 'danger')
    } finally {
      setLoading(false)
    }
  }

  const fetchReembedStatus = async () => {
    try {
      const resp = await axios.get('/api/settings/reembed-status')
      setReembedStatus(resp.data)
    } catch (e) {
      console.error('Error fetching re-embedding status', e)
    }
  }

  const fetchGeminiModels = async (apiKey?: string) => {
    try {
      setFetchingModels(true)
      let url = '/api/settings/models'
      if (apiKey) {
        url += `?api_key=${encodeURIComponent(apiKey)}`
      }
      const resp = await axios.get(url)
      setGeminiModels(resp.data.models || [])
    } catch (e) {
      console.error('Error listing Gemini models', e)
    } finally {
      setFetchingModels(false)
    }
  }

  const handleSettingChange = (key: string, value: any) => {
    setSettings((prev) => ({
      ...prev,
      [key]: value
    }))
  }

  const saveSettings = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      setSaving(true)
      const resp = await axios.post('/api/settings', { settings })
      setSettings(resp.data.settings)
      showNotification('System configurations updated successfully.', 'success')
      // Immediate fetch to see if re-embedding triggered
      setTimeout(fetchReembedStatus, 500)
    } catch (e: any) {
      console.error('Error saving settings', e)
      const msg = e.response?.data?.detail || 'Failed to persist settings.'
      showNotification(msg, 'danger')
    } finally {
      setSaving(false)
    }
  }

  const testGeminiKey = async () => {
    if (!settings.gemini_api_key) {
      setTestResult({ success: false, message: 'Please input a Gemini API Key first.' })
      return
    }
    try {
      setTestingKey(true)
      setTestResult(null)
      const resp = await axios.post('/api/settings/test', {
        api_key: settings.gemini_api_key
      })
      setTestResult({ success: true, message: resp.data.message })
      showNotification('Gemini API connection test passed!', 'success')
    } catch (e: any) {
      console.error('Error testing key', e)
      const msg = e.response?.data?.detail || 'API key connection failed.'
      setTestResult({ success: false, message: msg })
      showNotification('Gemini key validation failed.', 'danger')
    } finally {
      setTestingKey(false)
    }
  }

  const forceTriggerReembedding = async () => {
    if (window.confirm('Are you sure you want to force recalculate all semantic embeddings in the database? This may take some time depending on your database size.')) {
      try {
        const resp = await axios.post('/api/settings/reembed')
        showNotification(resp.data.message || 'Background re-embedding recalculation initiated.', 'success')
        setTimeout(fetchReembedStatus, 500)
      } catch (e: any) {
        showNotification('Failed to trigger database re-embedding.', 'danger')
      }
    }
  }

  if (loading) {
    return (
      <div className="h-96 rounded-lg border border-dashed border-surface-container-high bg-surface-container-lowest flex flex-col items-center justify-center p-6 space-y-4">
        <Loader2 className="w-10 h-10 text-primary animate-spin" />
        <h2 className="font-bold text-headline-sm text-neutral-dark">Loading Settings</h2>
        <p className="text-text-secondary text-body-sm text-center max-w-sm">
          Loading secure configuration variables from local LanceDB...
        </p>
      </div>
    )
  }

  const isGeminiActive = settings.provider === 'gemini'

  // Pre-determined local model lists for dropdowns
  const ollamaVisions = ['gemma4:e2b-it-qat', 'llama3.2-vision', 'phi3:vision', 'minicpm-v']
  const ollamaEmbeddings = ['embeddinggemma', 'nomic-embed-text', 'all-minilm']
  const geminiEmbeddings = ['gemini-embedding-002', 'gemini-embeddings-002', 'text-embedding-004']

  // Merge custom models with fetched models, ensuring no duplicates
  const getLlmOptions = () => {
    const customModels = [
      { id: 'gemma-4-26b-a4b-it', display_name: 'Gemma 4 26B A4B IT (Recommended)' },
      { id: 'gemma-4-31b-it', display_name: 'Gemma 4 31B IT' },
      { id: 'gemini-2.5-flash', display_name: 'Gemini 2.5 Flash' },
      { id: 'gemini-2.0-flash', display_name: 'Gemini 2.0 Flash' },
      { id: 'gemini-1.5-pro', display_name: 'Gemini 1.5 Pro' }
    ]

    const combined = [...customModels]
    geminiModels.forEach(m => {
      if (!combined.some(c => c.id === m.id)) {
        combined.push({
          id: m.id,
          display_name: m.display_name
        })
      }
    })
    return combined
  }

  const sections: { id: SettingsSection; label: string; icon: React.ElementType }[] = [
    { id: 'provider', label: 'Provider', icon: Cpu },
    { id: 'models', label: 'Pipeline Models', icon: isGeminiActive ? Sparkles : Server },
    { id: 'agent', label: 'Memory Agent', icon: Bot },
    { id: 'capture', label: 'Capture', icon: Camera },
    { id: 'database', label: 'Database', icon: Database },
    { id: 'mcp', label: 'MCP Integrations', icon: Plug },
    { id: 'prompts', label: 'Prompts', icon: FileTerminal },
    { id: 'skills', label: 'Claude Skills', icon: GraduationCap }
  ]

  return (
    <div className="font-sans space-y-6">
      {/* Page header */}
      <div>
        <div className="flex items-center gap-2 mb-1.5">
          <span className="text-[11px] font-semibold text-primary uppercase tracking-wider bg-accent-surface border border-primary/10 px-2.5 py-0.5 rounded font-mono select-none">
            System Configurations
          </span>
          {isGeminiActive ? (
            <span className="text-[11px] font-semibold text-success-green uppercase tracking-wider bg-success-green/10 border border-success-green/20 px-2 py-0.5 rounded font-mono flex items-center gap-1">
              <Sparkles className="w-3 h-3" /> Gemini Active
            </span>
          ) : (
            <span className="text-[11px] font-semibold text-text-secondary uppercase tracking-wider bg-surface-container-low border border-surface-container-high px-2 py-0.5 rounded font-mono flex items-center gap-1">
              <Server className="w-3 h-3" /> Ollama Local Only
            </span>
          )}
        </div>
        <h2 className="text-2xl md:text-3xl font-bold text-neutral-dark tracking-tight">Settings</h2>
        <p className="text-text-secondary text-body-md mt-1.5 max-w-2xl leading-relaxed">
          Transition between local-only Ollama models and Google Gemini cloud services. Sensitive API keys are hardware-encrypted locally.
        </p>
      </div>

      {/* Horizontal sub-tab navigation */}
      <div className="flex gap-1 border-b border-surface-container-high overflow-x-auto select-none">
        {sections.map((s) => {
          const Icon = s.icon
          const isActive = section === s.id
          return (
            <button
              key={s.id}
              type="button"
              onClick={() => setSection(s.id)}
              className={`h-10 px-4 text-action-md font-medium font-messina border-b-2 -mb-px flex items-center gap-2 shrink-0 transition-colors cursor-pointer ${
                isActive
                  ? 'border-primary text-primary'
                  : 'border-transparent text-text-secondary hover:text-neutral-dark'
              }`}
            >
              <Icon className="w-4 h-4" /> {s.label}
            </button>
          )
        })}
      </div>

      {section === 'mcp' ? (
        <McpSettings showNotification={showNotification} />
      ) : section === 'prompts' ? (
        <PromptSettings showNotification={showNotification} />
      ) : section === 'skills' ? (
        <SkillSettings showNotification={showNotification} />
      ) : (
      <form onSubmit={saveSettings} className="space-y-6">
        {/* SECTION: Provider */}
        <div className={`max-w-3xl space-y-6 ${section === 'provider' ? '' : 'hidden'}`}>
          {/* Provider Selection Card */}
          <div className="bg-surface-container-lowest border border-surface-container-high p-6 rounded-lg space-y-5">
            <h3 className="font-bold text-headline-sm text-neutral-dark flex items-center gap-2 border-b border-surface-container-high pb-3">
              <Cpu className="w-5 h-5 text-primary" /> Active Pipeline Provider
            </h3>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Local Ollama Option */}
              <label
                className={`p-4 rounded border-2 cursor-pointer transition-all flex flex-col justify-between gap-2 h-36 ${
                  settings.provider === 'ollama'
                    ? 'border-primary bg-accent-surface/30'
                    : 'border-surface-container-high bg-surface-container-low hover:border-outline'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-bold text-neutral-dark text-body-md">Ollama Local</span>
                  <input
                    type="radio"
                    name="pipeline_provider"
                    checked={settings.provider === 'ollama'}
                    onChange={() => handleSettingChange('provider', 'ollama')}
                    className="w-4 h-4 text-primary"
                  />
                </div>
                <p className="text-text-secondary text-body-sm leading-relaxed">
                  100% private, on-device offline extraction. Requires running Ollama on your host.
                </p>
                <span className="text-[10px] font-semibold text-text-secondary uppercase tracking-wider font-mono">
                  Zero Cloud Cost
                </span>
              </label>

              {/* Gemini Cloud Option */}
              <label
                className={`p-4 rounded border-2 cursor-pointer transition-all flex flex-col justify-between gap-2 h-36 ${
                  settings.provider === 'gemini'
                    ? 'border-primary bg-accent-surface/30'
                    : 'border-surface-container-high bg-surface-container-low hover:border-outline'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-bold text-neutral-dark text-body-md flex items-center gap-1">
                    Google Gemini <Sparkles className="w-3.5 h-3.5 text-primary" />
                  </span>
                  <input
                    type="radio"
                    name="pipeline_provider"
                    checked={settings.provider === 'gemini'}
                    onChange={() => handleSettingChange('provider', 'gemini')}
                    className="w-4 h-4 text-primary"
                  />
                </div>
                <p className="text-text-secondary text-body-sm leading-relaxed">
                  Premium fast ingestion, high-fidelity OCR, and massive context lengths.
                </p>
                <span className="text-[10px] font-semibold text-primary uppercase tracking-wider font-mono">
                  API Key Required
                </span>
              </label>
            </div>
          </div>

          {/* Google Gemini Credentials Card (Conditional) */}
          <div className="bg-surface-container-lowest border border-surface-container-high p-6 rounded-lg space-y-5">
            <h3 className="font-bold text-headline-sm text-neutral-dark flex items-center gap-2 border-b border-surface-container-high pb-3">
              <Key className="w-5 h-5 text-primary" /> Google Gemini Credentials
            </h3>

            <div className="space-y-4">
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label htmlFor="geminiApiKeyInput" className="text-body-sm font-semibold text-text-secondary">
                    Gemini API Key
                  </label>
                  <span className="text-[10px] font-medium text-text-secondary flex items-center gap-1">
                    <Lock className="w-3 h-3 text-outline" /> Local AES-256 Encrypted
                  </span>
                </div>
                <div className="relative">
                  <input
                    id="geminiApiKeyInput"
                    name="geminiApiKeyInput"
                    type={showKey ? 'text' : 'password'}
                    value={settings.gemini_api_key}
                    onChange={(e) => handleSettingChange('gemini_api_key', e.target.value)}
                    placeholder="Enter your Gemini API Key..."
                    className="w-full bg-surface-container-low border border-surface-container-high h-11 pl-4 pr-12 rounded text-body-md text-neutral-dark font-mono outline-none focus:border-primary transition-colors"
                  />
                  <button
                    type="button"
                    onClick={() => setShowKey(!showKey)}
                    className="absolute right-3.5 top-1/2 -translate-y-1/2 text-text-secondary hover:text-neutral-dark transition-colors cursor-pointer"
                  >
                    {showKey ? <EyeOff className="w-4.5 h-4.5" /> : <Eye className="w-4.5 h-4.5" />}
                  </button>
                </div>
                <p className="text-technical-sm text-text-secondary leading-normal">
                  Don't have a key? Get one from the{' '}
                  <a
                    href="https://aistudio.google.com/"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary hover:underline font-bold"
                  >
                    Google AI Studio
                  </a>.
                </p>
              </div>

              {/* Rate Limit Protection */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label htmlFor="geminiRateLimitDelayInput" className="text-body-sm font-semibold text-text-secondary">
                    Free-Tier RPM Shield (Seconds)
                  </label>
                  <input
                    id="geminiRateLimitDelayInput"
                    name="geminiRateLimitDelayInput"
                    type="number"
                    step="0.1"
                    min="0"
                    value={settings.gemini_rate_limit_delay}
                    onChange={(e) => handleSettingChange('gemini_rate_limit_delay', parseFloat(e.target.value) || 0)}
                    className="w-full bg-surface-container-low border border-surface-container-high h-11 px-4 rounded text-body-md text-neutral-dark outline-none focus:border-primary font-mono transition-colors"
                  />
                  <p className="text-[11px] text-text-secondary">
                    Proactive request spacing. Recommended: <strong>4.0s</strong> for 15 RPM limits.
                  </p>
                </div>

                <div className="flex items-end pb-1">
                  <button
                    type="button"
                    onClick={testGeminiKey}
                    disabled={testingKey || !settings.gemini_api_key}
                    className="w-full bg-accent-surface hover:bg-surface-container text-primary font-bold h-11 rounded border border-primary/20 transition-all flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50"
                  >
                    {testingKey ? (
                      <>
                        <Loader2 className="w-4.5 h-4.5 animate-spin" />
                        Validating...
                      </>
                    ) : (
                      <>
                        <Activity className="w-4.5 h-4.5" />
                        Test Connection
                      </>
                    )}
                  </button>
                </div>
              </div>

              {/* API validation result alert */}
              {testResult && (
                <div
                  className={`p-4 rounded border text-body-sm flex items-start gap-3 leading-relaxed animate-fade-in ${
                    testResult.success
                      ? 'bg-success-green/10 border-success-green/20 text-success-green'
                      : 'bg-error-container/30 border-error-container text-error'
                  }`}
                >
                  {testResult.success ? (
                    <CheckCircle2 className="w-5 h-5 text-success-green shrink-0 mt-0.5" />
                  ) : (
                    <AlertCircle className="w-5 h-5 text-error shrink-0 mt-0.5" />
                  )}
                  <div>
                    <strong className="block font-bold">
                      {testResult.success ? 'Credentials Verified' : 'Connection Failed'}
                    </strong>
                    {testResult.message}
                  </div>
                </div>
              )}
            </div>
          </div>

        </div>

        {/* SECTION: Pipeline Models */}
        <div className={`max-w-3xl space-y-6 ${section === 'models' ? '' : 'hidden'}`}>
          {/* Model Specific Settings */}
          {isGeminiActive ? (
            /* Gemini cloud model config card */
            <div className="bg-surface-container-lowest border border-surface-container-high p-6 rounded-lg space-y-5">
              <h3 className="font-bold text-headline-sm text-neutral-dark flex items-center gap-2 border-b border-surface-container-high pb-3">
                <Sparkles className="w-5 h-5 text-primary" /> Gemini Engine Configurations
              </h3>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label htmlFor="geminiLlmModelSelect" className="text-body-sm font-semibold text-text-secondary">
                    Multimodal LLM Model
                  </label>
                  <select
                    id="geminiLlmModelSelect"
                    name="geminiLlmModelSelect"
                    value={settings.gemini_llm_model}
                    onChange={(e) => handleSettingChange('gemini_llm_model', e.target.value)}
                    className="w-full bg-surface-container-low border border-surface-container-high h-11 px-3 rounded text-body-md text-neutral-dark outline-none focus:border-primary transition-colors cursor-pointer"
                  >
                    {getLlmOptions().map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.display_name}
                      </option>
                    ))}
                  </select>
                  {fetchingModels && (
                    <span className="text-[10px] text-primary flex items-center gap-1 pt-0.5">
                      <Loader2 className="w-3 h-3 animate-spin" /> Querying API models...
                    </span>
                  )}
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="geminiEmbeddingModelSelect" className="text-body-sm font-semibold text-text-secondary">
                    Embedding Model
                  </label>
                  <select
                    id="geminiEmbeddingModelSelect"
                    name="geminiEmbeddingModelSelect"
                    value={settings.gemini_embedding_model}
                    onChange={(e) => handleSettingChange('gemini_embedding_model', e.target.value)}
                    className="w-full bg-surface-container-low border border-surface-container-high h-11 px-3 rounded text-body-md text-neutral-dark outline-none focus:border-primary transition-colors cursor-pointer"
                  >
                    {geminiEmbeddings.map((emb) => (
                      <option key={emb} value={emb}>
                        {emb} (3072 dimensions)
                      </option>
                    ))}
                  </select>
                  <p className="text-[10px] text-error flex items-start gap-1 font-semibold leading-normal pt-0.5">
                    <ShieldAlert className="w-3.5 h-3.5 shrink-0 mt-0.5" /> Re-embedding will run on change!
                  </p>
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="geminiContextSizeInput" className="text-body-sm font-semibold text-text-secondary">
                    Configured Context Size
                  </label>
                  <input
                    id="geminiContextSizeInput"
                    name="geminiContextSizeInput"
                    type="number"
                    value={settings.gemini_context_size}
                    onChange={(e) => handleSettingChange('gemini_context_size', parseInt(e.target.value) || 0)}
                    className="w-full bg-surface-container-low border border-surface-container-high h-11 px-4 rounded text-body-md text-neutral-dark outline-none focus:border-primary font-mono transition-colors"
                  />
                  <span className="text-[11px] text-text-secondary">
                    Recommended: <strong>1,048,576</strong> characters.
                  </span>
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="ocrProviderSelect" className="text-body-sm font-semibold text-text-secondary">
                    OCR Provider
                  </label>
                  <select
                    id="ocrProviderSelect"
                    name="ocrProviderSelect"
                    value={settings.ocr_provider || 'ollama'}
                    onChange={(e) => handleSettingChange('ocr_provider', e.target.value)}
                    className="w-full bg-surface-container-low border border-surface-container-high h-11 px-3 rounded text-body-md text-neutral-dark outline-none focus:border-primary transition-colors cursor-pointer"
                  >
                    <option value="ollama">Ollama (Local GLM-OCR)</option>
                    <option value="gemini">Gemini (Cloud OCR)</option>
                  </select>
                  <p className="text-[11px] text-text-secondary">
                    Select where screenshot text extraction takes place.
                  </p>
                </div>

                <div className="p-4 bg-surface-container-low rounded border border-surface-container-high text-body-sm text-text-secondary flex items-start gap-2 leading-relaxed md:col-span-2">
                  <CheckCircle2 className="w-4.5 h-4.5 text-success-green shrink-0 mt-0.5" />
                  <div>
                    <strong>Pipeline Optimization:</strong> If both main provider and OCR provider are set to Gemini, local OCR is bypassed, and Phase 2 combines both OCR and Vision extraction in a single multimodal request to save API quota and time.
                  </div>
                </div>
              </div>
            </div>
          ) : (
            /* Local Ollama model config card */
            <div className="bg-surface-container-lowest border border-surface-container-high p-6 rounded-lg space-y-5">
              <h3 className="font-bold text-headline-sm text-neutral-dark flex items-center gap-2 border-b border-surface-container-high pb-3">
                <Server className="w-5 h-5 text-primary" /> Local Ollama Engine Configs
              </h3>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label htmlFor="ollamaOcrModelInput" className="text-body-sm font-semibold text-text-secondary">
                    Local OCR Model (Phase 1)
                  </label>
                  <input
                    id="ollamaOcrModelInput"
                    name="ollamaOcrModelInput"
                    type="text"
                    value={settings.ollama_ocr_model}
                    onChange={(e) => handleSettingChange('ollama_ocr_model', e.target.value)}
                    className="w-full bg-surface-container-low border border-surface-container-high h-11 px-4 rounded text-body-md text-neutral-dark outline-none focus:border-primary font-mono transition-colors"
                  />
                  <p className="text-[11px] text-text-secondary">
                    Default: <strong>glm-ocr:q8_0</strong>
                  </p>
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="ollamaVisionModelSelect" className="text-body-sm font-semibold text-text-secondary">
                    Local Vision Model (Phase 2)
                  </label>
                  <select
                    id="ollamaVisionModelSelect"
                    name="ollamaVisionModelSelect"
                    value={settings.ollama_vision_model}
                    onChange={(e) => handleSettingChange('ollama_vision_model', e.target.value)}
                    className="w-full bg-surface-container-low border border-surface-container-high h-11 px-3 rounded text-body-md text-neutral-dark outline-none focus:border-primary transition-colors cursor-pointer"
                  >
                    {ollamaVisions.map((v) => (
                      <option key={v} value={v}>
                        {v}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="ollamaEmbeddingModelSelect" className="text-body-sm font-semibold text-text-secondary">
                    Local Embedding Model (Phase 3)
                  </label>
                  <select
                    id="ollamaEmbeddingModelSelect"
                    name="ollamaEmbeddingModelSelect"
                    value={settings.ollama_embedding_model}
                    onChange={(e) => handleSettingChange('ollama_embedding_model', e.target.value)}
                    className="w-full bg-surface-container-low border border-surface-container-high h-11 px-3 rounded text-body-md text-neutral-dark outline-none focus:border-primary transition-colors cursor-pointer"
                  >
                    {ollamaEmbeddings.map((emb) => (
                      <option key={emb} value={emb}>
                        {emb} (768 dimensions)
                      </option>
                    ))}
                  </select>
                  <p className="text-[10px] text-error flex items-start gap-1 font-semibold leading-normal pt-0.5">
                    <ShieldAlert className="w-3.5 h-3.5 shrink-0 mt-0.5" /> Re-embedding will run on change!
                  </p>
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="ollamaContextSizeInput" className="text-body-sm font-semibold text-text-secondary">
                    Ollama Context Size
                  </label>
                  <input
                    id="ollamaContextSizeInput"
                    name="ollamaContextSizeInput"
                    type="number"
                    value={settings.ollama_context_size}
                    onChange={(e) => handleSettingChange('ollama_context_size', parseInt(e.target.value) || 0)}
                    className="w-full bg-surface-container-low border border-surface-container-high h-11 px-4 rounded text-body-md text-neutral-dark outline-none focus:border-primary font-mono transition-colors"
                  />
                  <span className="text-[11px] text-text-secondary">
                    Default context boundary: <strong>8192</strong> characters.
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* SECTION: Memory Agent */}
        <div className={`max-w-3xl space-y-6 ${section === 'agent' ? '' : 'hidden'}`}>
          {/* Interactive Memory Agent Config */}
          <div className="bg-surface-container-lowest border border-surface-container-high p-6 rounded-lg space-y-5">
            <h3 className="font-bold text-headline-sm text-neutral-dark flex items-center gap-2 border-b border-surface-container-high pb-3">
              <Sparkles className="w-5 h-5 text-primary" /> Memory Agent Settings
            </h3>

            <div className="space-y-4">
              {/* Agent Provider */}
              <div className="space-y-1.5">
                <label htmlFor="agentProviderSelect" className="text-body-sm font-semibold text-text-secondary">
                  Agent Reasoner Provider
                </label>
                <select
                  id="agentProviderSelect"
                  name="agentProviderSelect"
                  value={settings.agent_provider}
                  onChange={(e) => handleSettingChange('agent_provider', e.target.value)}
                  className="w-full bg-surface-container-low border border-surface-container-high h-11 px-3 rounded text-body-md text-neutral-dark outline-none focus:border-primary transition-colors cursor-pointer font-sans"
                >
                  <option value="ollama">Local Ollama</option>
                  <option value="gemini">Google Gemini Cloud</option>
                </select>
              </div>

              {/* Agent Model */}
              <div className="space-y-1.5">
                <label htmlFor="agentModelInput" className="text-body-sm font-semibold text-text-secondary">
                  Agent Logic Model
                </label>
                {settings.agent_provider === 'gemini' ? (
                  <select
                    id="agentModelSelect"
                    name="agentModelSelect"
                    value={settings.agent_model}
                    onChange={(e) => handleSettingChange('agent_model', e.target.value)}
                    className="w-full bg-surface-container-low border border-surface-container-high h-11 px-3 rounded text-body-md text-neutral-dark outline-none focus:border-primary transition-colors cursor-pointer"
                  >
                    {getLlmOptions().map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.display_name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    id="agentModelInput"
                    name="agentModelInput"
                    type="text"
                    value={settings.agent_model}
                    onChange={(e) => handleSettingChange('agent_model', e.target.value)}
                    className="w-full bg-surface-container-low border border-surface-container-high h-11 px-4 rounded text-body-md text-neutral-dark outline-none focus:border-primary font-mono transition-colors"
                  />
                )}
                <p className="text-[11px] text-text-secondary">
                  Model executing ReAct tool loops for chatbot responses.
                </p>
              </div>

              {/* Agent Context & Buffer limiters */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label htmlFor="agentContextSizeInput" className="text-body-sm font-semibold text-text-secondary">
                    Agent Context size
                  </label>
                  <input
                    id="agentContextSizeInput"
                    name="agentContextSizeInput"
                    type="number"
                    value={settings.agent_context_size}
                    onChange={(e) => handleSettingChange('agent_context_size', parseInt(e.target.value) || 0)}
                    className="w-full bg-surface-container-low border border-surface-container-high h-11 px-4 rounded text-body-md text-neutral-dark outline-none focus:border-primary font-mono transition-colors"
                  />
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="maxToolResultCharsInput" className="text-body-sm font-semibold text-text-secondary">
                    Max Tool Response Cutoff
                  </label>
                  <input
                    id="maxToolResultCharsInput"
                    name="maxToolResultCharsInput"
                    type="number"
                    value={settings.max_tool_result_chars}
                    onChange={(e) => handleSettingChange('max_tool_result_chars', parseInt(e.target.value) || 0)}
                    className="w-full bg-surface-container-low border border-surface-container-high h-11 px-4 rounded text-body-md text-neutral-dark outline-none focus:border-primary font-mono transition-colors"
                  />
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="maxSummarizeChunkCharsInput" className="text-body-sm font-semibold text-text-secondary">
                    Summarization Chunk Character Limit
                  </label>
                  <input
                    id="maxSummarizeChunkCharsInput"
                    name="maxSummarizeChunkCharsInput"
                    type="number"
                    min="1000"
                    value={settings.max_summarize_chunk_chars ?? 15000}
                    onChange={(e) => handleSettingChange('max_summarize_chunk_chars', Math.max(1000, parseInt(e.target.value) || 15000))}
                    className="w-full bg-surface-container-low border border-surface-container-high h-11 px-4 rounded text-body-md text-neutral-dark outline-none focus:border-primary font-mono transition-colors"
                  />
                </div>
              </div>
            </div>
          </div>

        </div>

        {/* SECTION: Capture */}
        <div className={`max-w-3xl space-y-6 ${section === 'capture' ? '' : 'hidden'}`}>
          <CaptureSettings settings={settings} handleSettingChange={handleSettingChange} />
        </div>

        {/* SECTION: Database */}
        <div className={`max-w-3xl space-y-6 ${section === 'database' ? '' : 'hidden'}`}>
          {/* Database Re-embedding Progress and Controls */}
          <div className="bg-surface-container-lowest border border-surface-container-high p-6 rounded-lg space-y-4">
            <h3 className="font-bold text-headline-sm text-neutral-dark flex items-center gap-2 border-b border-surface-container-high pb-3">
              <Database className="w-5 h-5 text-primary" /> Active Vector Alignment
            </h3>

            {reembedStatus.is_running ? (
              /* PROGRESSING STATE */
              <div className="space-y-4 animate-pulse-slow">
                <div className="p-4 bg-accent-surface/20 border border-primary/20 rounded flex items-start gap-3 text-body-sm text-text-secondary">
                  <Loader2 className="w-5 h-5 text-primary animate-spin shrink-0 mt-0.5" />
                  <div>
                    <strong className="block font-bold text-neutral-dark">Recalculating Embeddings...</strong>
                    A background database-wide migration is actively re-indexing all historical data records using the new active coordinate models.
                  </div>
                </div>

                <div className="space-y-2">
                  <div className="flex justify-between items-center text-technical-sm font-mono text-text-secondary">
                    <span>Re-embedding Progress</span>
                    <span>
                      {reembedStatus.processed_records} / {reembedStatus.total_records} (
                      {reembedStatus.total_records > 0
                        ? Math.round((reembedStatus.processed_records / reembedStatus.total_records) * 100)
                        : 0}
                      %)
                    </span>
                  </div>
                  <div className="w-full h-3 bg-surface-container rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-primary via-surface-tint to-success-green rounded-full transition-all duration-300"
                      style={{
                        width: `${
                          reembedStatus.total_records > 0
                            ? (reembedStatus.processed_records / reembedStatus.total_records) * 100
                            : 0
                        }%`
                      }}
                    ></div>
                  </div>
                  <span className="text-[10px] text-text-secondary block font-mono text-right">
                    Active: {reembedStatus.current_model}
                  </span>
                </div>
              </div>
            ) : (
              /* STATIC COMPLETED / IDLE STATE */
              <div className="space-y-4">
                <div className="p-4 bg-surface-container-low border border-surface-container-high rounded text-body-sm text-text-secondary space-y-2 leading-relaxed">
                  <div className="flex items-center gap-2 text-success-green font-semibold">
                    <CheckCircle2 className="w-4.5 h-4.5" />
                    <span>Database Synced</span>
                  </div>
                  <p>
                    All database records are currently aligned. If you save modifications that alter the active embedding engine above, a background migration will initiate automatically.
                  </p>
                  <p className="text-technical-sm font-mono pt-1 text-neutral-dark">
                    Current layout: <strong>{reembedStatus.current_model || 'Local Ollama:embeddinggemma'}</strong>
                  </p>
                </div>

                <button
                  type="button"
                  onClick={forceTriggerReembedding}
                  className="w-full bg-surface-container-low hover:bg-surface-container border border-surface-container-high text-neutral-dark text-action-md font-semibold h-11 rounded transition-all flex items-center justify-center gap-2 cursor-pointer"
                >
                  <RefreshCw className="w-4 h-4" />
                  Force Vector Recalculation
                </button>
              </div>
            )}

            {reembedStatus.error && (
              <div className="p-3 bg-error-container/20 border border-error-container text-error text-technical-sm rounded flex items-start gap-2.5">
                <AlertCircle className="w-4.5 h-4.5 shrink-0 mt-0.5" />
                <div>
                  <strong className="block font-semibold">Migration Error:</strong>
                  {reembedStatus.error}
                </div>
              </div>
            )}
          </div>

        </div>

        {/* Shared action buttons footer */}
        <div className="flex items-center gap-4 justify-end pt-5 border-t border-surface-container-high">
          <button
            type="button"
            onClick={fetchSettings}
            disabled={saving}
            className="bg-surface-container-low hover:bg-surface-container border border-surface-container-high text-neutral-dark text-action-md font-bold py-3 px-5 rounded h-11 transition-all cursor-pointer"
          >
            Reset Changes
          </button>
          <button
            type="submit"
            disabled={saving}
            className="bg-primary hover:opacity-90 border border-primary text-on-primary text-action-md font-bold py-3 px-6 rounded h-11 transition-all flex items-center gap-2 cursor-pointer disabled:opacity-55 shadow-none"
          >
            {saving ? (
              <>
                <Loader2 className="w-4.5 h-4.5 animate-spin" />
                Saving Configuration...
              </>
            ) : (
              <>
                <Settings className="w-4.5 h-4.5" />
                Save configurations
              </>
            )}
          </button>
        </div>
      </form>
      )}
    </div>
  )
}
