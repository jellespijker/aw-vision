import React from 'react'
import { Layers, Sun, Moon, RefreshCw } from 'lucide-react'
import type { DaemonStatus } from '../types'

interface HeaderProps {
  darkMode: boolean
  setDarkMode: (val: boolean) => void
  serverOnline: boolean
  status: DaemonStatus | null
  checkServerStatus: () => void
}

export const Header: React.FC<HeaderProps> = ({
  darkMode,
  setDarkMode,
  serverOnline,
  status,
  checkServerStatus
}) => {
  return (
    <header className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8 pb-6 border-b border-surface-container-high">
      <div>
        <div className="flex items-center gap-2.5 mb-1.5">
          <Layers className={`w-7 h-7 ${darkMode ? 'text-inverse-primary' : 'text-primary'}`} />
          <h1 className="text-2xl font-semibold tracking-tight font-sans text-neutral-dark">
            Visual &amp; Semantic Memory
          </h1>
        </div>
        <p className="text-text-secondary text-body-sm max-w-2xl font-sans">
          Secure, local-first computer history pipeline. Screenshot capture loops, optical text models, and vector embeddings stored completely on-device.
        </p>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        {/* Theme Toggle Button */}
        <button
          onClick={() => setDarkMode(!darkMode)}
          className="h-10 w-10 rounded border border-surface-container-high bg-surface-container-lowest hover:bg-surface-container-low text-text-secondary transition-colors flex items-center justify-center select-none cursor-pointer"
          title={darkMode ? "Switch to Light Theme" : "Switch to Dark Theme"}
        >
          {darkMode ? <Sun className="w-4 h-4 text-attention-yellow" /> : <Moon className="w-4 h-4 text-primary" />}
        </button>

        {serverOnline && status && (
          <>
            {/* Active Daemon Indicators */}
            <div className="bg-surface-container-low border border-surface-container-high px-3 h-10 rounded-full flex items-center gap-2 text-indicator-bold text-neutral-dark font-messina text-action-md" title="aw-watcher activity status">
              <span className={`w-2.5 h-2.5 rounded-full ${status.watcher_running ? 'bg-success-green' : 'bg-danger-primary'}`}></span>
              <span>Watcher: {status.watcher_running ? 'ACTIVE' : 'STOPPED'}</span>
            </div>

            <div className="bg-surface-container-low border border-surface-container-high px-3 h-10 rounded-full flex items-center gap-2 text-indicator-bold text-neutral-dark font-messina text-action-md" title="Bulk processor status">
              <span className={`w-2.5 h-2.5 rounded-full ${status.processor_running ? 'bg-success-green animate-pulse-slow' : 'bg-disabled'}`}></span>
              <span>Processor: {status.processor_running ? 'ACTIVE' : 'IDLE'}</span>
            </div>

            <div className="bg-surface-container-low border border-surface-container-high px-3 h-10 rounded-full flex items-center gap-2 text-indicator-bold text-neutral-dark font-messina text-action-md" title="ActivityWatch core server connection status (port 5600)">
              <span className={`w-2.5 h-2.5 rounded-full ${status.aw_server_online ? 'bg-success-green' : 'bg-danger-primary'}`}></span>
              <span>aw-server: {status.aw_server_online ? 'ONLINE' : 'OFFLINE'}</span>
            </div>

            <div className="bg-surface-container-low border border-surface-container-high px-3 h-10 rounded-full flex items-center gap-2 text-indicator-bold text-neutral-dark font-messina text-action-md" title="Ollama API service connection status (port 11434)">
              <span className={`w-2.5 h-2.5 rounded-full ${status.ollama_online ? 'bg-success-green' : 'bg-danger-primary'}`}></span>
              <span>Ollama: {status.ollama_online ? 'ONLINE' : 'OFFLINE'}</span>
            </div>

            <div className="bg-surface-container-low border border-surface-container-high px-3 h-10 rounded-full flex items-center gap-2 text-indicator-bold text-neutral-dark font-messina text-action-md" title="Wayland capture utility spectacle/grim availability">
              <span className={`w-2.5 h-2.5 rounded-full ${status.capture_cli_available ? 'bg-success-green' : 'bg-danger-primary'}`}></span>
              <span>Capture CLI: {status.capture_cli_available ? 'AVAILABLE' : 'MISSING'}</span>
            </div>

            <button
              onClick={checkServerStatus}
              className="h-10 w-10 rounded border border-surface-container-high bg-surface-container-lowest hover:bg-surface-container-low text-text-secondary transition-colors flex items-center justify-center select-none cursor-pointer"
              title="Refresh Daemon Status"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </>
        )}
      </div>
    </header>
  )
}
