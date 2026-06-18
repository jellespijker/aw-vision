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

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
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
}

export interface Project {
  project_number: string
  description: string
  work_entailment: string
  tracked_hours: number
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
