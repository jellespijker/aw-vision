export interface SystemLoad {
  cpu_percent: number
  memory_percent: number
}

export interface DaemonStatus {
  watcher_running: boolean
  processor_running: boolean
  pending_queue_size: number
  processed_database_size: number
  processing_ids?: string[]
  is_processing?: boolean
  current_batch_total?: number
  current_batch_processed?: number
  current_rec_id?: string | null
  current_stage?: string | null
  last_error?: string | null
  system_load: SystemLoad
  aw_server_online?: boolean
  ollama_online?: boolean
  capture_cli_available?: boolean
  capture_cli_details?: {
    spectacle: boolean
    grim: boolean
  }
  agent_provider?: string
  agent_model?: string
}

export interface ToolEvent {
  tool: string
  args: string
  source: 'builtin' | 'mcp'
  result_preview: string
  duration_seconds?: number
  error?: boolean
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  tool_events?: ToolEvent[]
}

export interface HistoryRecord {
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
  user_context?: string | null
  analysis_reasoning?: string | null
  classification_confidence?: 'direct' | 'thematic' | 'none' | null
}

export interface Project {
  project_number: string
  description: string
  work_entailment: string
  tracked_hours: number
  is_active?: boolean
  created_at?: number
}

export interface TimelineEntry {
  label: string
  count: number
  page: number
  timestamp: number
}

export interface TimelineBin {
  start_time: number
  end_time: number
  duration_seconds: number
}

export interface ProjectTimeline {
  project_number: string
  description: string
  color: string
  total_duration_seconds: number
  bins: TimelineBin[]
}

export interface TimelineHeader {
  timestamp: number
  label: string
}

export interface ProjectsTimelineResponse {
  projects: ProjectTimeline[]
  timeline_headers: TimelineHeader[]
}

export interface PhaseStats {
  mean: number
  min: number
  max: number
  count: number
}

export interface ProcessingStats {
  ocr: PhaseStats
  vision: PhaseStats
  embedding: PhaseStats
  total: PhaseStats
}

