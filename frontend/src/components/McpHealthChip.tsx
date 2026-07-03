import React from 'react'
import { AlertCircle } from 'lucide-react'

export interface McpHealth {
  state: 'ok' | 'degraded' | 'open'
  consecutive_failures: number
  last_error: string | null
  retry_at: number | null
}

/** Circuit-breaker status chip for an MCP server (hidden while healthy). */
export const McpHealthChip: React.FC<{ health?: McpHealth }> = ({ health }) => {
  if (!health || health.state === 'ok') return null
  const open = health.state === 'open'
  return (
    <span
      title={health.last_error || undefined}
      className={`text-[10px] font-semibold uppercase tracking-wider font-mono px-2 py-0.5 rounded border flex items-center gap-1 ${
        open
          ? 'bg-danger-surface border-danger-primary/30 text-danger-primary'
          : 'bg-warning-light border-surface-container-high text-neutral-dark'
      }`}
    >
      <AlertCircle className="w-3 h-3" />
      {open ? 'Unreachable' : `${health.consecutive_failures} failures`}
    </span>
  )
}
