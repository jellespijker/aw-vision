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
