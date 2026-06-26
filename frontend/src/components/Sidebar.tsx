import React from 'react'
import {
  Layers,
  Bot,
  Image as ImageIcon,
  FileText,
  Activity,
  Settings,
  Sun,
  Moon,
  RefreshCw
} from 'lucide-react'
import type { DaemonStatus } from '../types'

type TabId = 'chat' | 'gallery' | 'projects' | 'pipeline' | 'settings'

interface SidebarProps {
  activeTab: TabId
  setActiveTab: (tab: TabId) => void
  totalCount: number
  darkMode: boolean
  setDarkMode: (val: boolean) => void
  serverOnline: boolean
  status: DaemonStatus | null
  checkServerStatus: () => void
}

interface NavItem {
  id: TabId
  label: string
  icon: React.ElementType
  badge?: string
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  setActiveTab,
  totalCount,
  darkMode,
  setDarkMode,
  serverOnline,
  status,
  checkServerStatus
}) => {
  const navItems: NavItem[] = [
    { id: 'chat', label: 'Ask Memory Agent', icon: Bot },
    { id: 'gallery', label: 'Screenshot Library', icon: ImageIcon, badge: totalCount > 0 ? String(totalCount) : undefined },
    { id: 'projects', label: 'Project Mapping', icon: FileText },
    { id: 'pipeline', label: 'System Pipeline', icon: Activity },
    { id: 'settings', label: 'Settings', icon: Settings }
  ]

  const indicators = status
    ? [
        { label: 'Watcher', ok: status.watcher_running, online: 'ACTIVE', offline: 'STOPPED' },
        { label: 'Processor', ok: status.processor_running, online: 'ACTIVE', offline: 'IDLE' },
        { label: 'aw-server', ok: status.aw_server_online, online: 'ONLINE', offline: 'OFFLINE' },
        { label: 'Ollama', ok: status.ollama_online, online: 'ONLINE', offline: 'OFFLINE' },
        { label: 'Capture CLI', ok: status.capture_cli_available, online: 'AVAILABLE', offline: 'MISSING' }
      ]
    : []

  return (
    <aside className="w-full lg:w-[264px] lg:shrink-0 lg:h-screen lg:sticky lg:top-0 flex flex-col bg-surface-container-lowest border-b lg:border-b-0 lg:border-r border-surface-container-high">
      {/* Brand */}
      <div className="px-5 py-5 border-b border-surface-container-high">
        <div className="flex items-center gap-2.5">
          <Layers className={`w-7 h-7 shrink-0 ${darkMode ? 'text-inverse-primary' : 'text-primary'}`} />
          <div className="min-w-0">
            <h1 className="text-headline-sm font-semibold tracking-tight text-neutral-dark truncate">
              Visual Memory
            </h1>
            <p className="text-[11px] text-text-secondary font-messina truncate">Local-first capture pipeline</p>
          </div>
        </div>
      </div>

      {/* Primary navigation */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        {navItems.map((item) => {
          const Icon = item.icon
          const isActive = activeTab === item.id
          return (
            <button
              key={item.id}
              id={`nav-${item.id}`}
              onClick={() => setActiveTab(item.id)}
              className={`w-full h-10 px-3 rounded text-action-md font-medium font-messina flex items-center gap-3 transition-colors select-none cursor-pointer ${
                isActive
                  ? 'bg-accent-surface text-primary'
                  : 'text-text-secondary hover:text-neutral-dark hover:bg-surface-container-low'
              }`}
            >
              <Icon className={`w-4.5 h-4.5 shrink-0 ${isActive ? 'text-primary' : ''}`} />
              <span className="flex-1 text-left truncate">{item.label}</span>
              {item.badge && (
                <span
                  className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${
                    isActive
                      ? 'bg-primary/10 text-primary'
                      : 'bg-surface-container text-text-secondary'
                  }`}
                >
                  {item.badge}
                </span>
              )}
            </button>
          )
        })}
      </nav>

      {/* Daemon status + controls */}
      <div className="px-3 py-4 border-t border-surface-container-high space-y-3">
        {serverOnline && status && (
          <div className="px-2 space-y-1.5">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-[10px] font-semibold text-text-secondary uppercase tracking-wider font-messina select-none">
                System Status
              </span>
              <button
                onClick={checkServerStatus}
                className="text-text-secondary hover:text-neutral-dark transition-colors cursor-pointer"
                title="Refresh Daemon Status"
              >
                <RefreshCw className="w-3.5 h-3.5" />
              </button>
            </div>
            {indicators.map((ind) => (
              <div key={ind.label} className="flex items-center justify-between text-[11px] font-messina" title={ind.label}>
                <span className="text-text-secondary">{ind.label}</span>
                <span className="flex items-center gap-1.5 text-neutral-dark font-medium">
                  <span className={`w-2 h-2 rounded-full ${ind.ok ? 'bg-success-green' : 'bg-danger-primary'}`}></span>
                  {ind.ok ? ind.online : ind.offline}
                </span>
              </div>
            ))}
          </div>
        )}

        <button
          onClick={() => setDarkMode(!darkMode)}
          className="w-full h-10 px-3 rounded border border-surface-container-high bg-surface-container-lowest hover:bg-surface-container-low text-text-secondary transition-colors flex items-center gap-3 select-none cursor-pointer text-action-md font-medium font-messina"
          title={darkMode ? 'Switch to Light Theme' : 'Switch to Dark Theme'}
        >
          {darkMode ? (
            <Sun className="w-4.5 h-4.5 text-attention-yellow" />
          ) : (
            <Moon className="w-4.5 h-4.5 text-primary" />
          )}
          {darkMode ? 'Light Theme' : 'Dark Theme'}
        </button>
      </div>
    </aside>
  )
}
