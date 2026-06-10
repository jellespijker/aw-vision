import React from 'react'
import { Bot, Image as ImageIcon, FileText, Activity, Settings } from 'lucide-react'

interface TabsProps {
  activeTab: 'chat' | 'gallery' | 'projects' | 'pipeline' | 'settings'
  setActiveTab: (tab: 'chat' | 'gallery' | 'projects' | 'pipeline' | 'settings') => void
  totalCount: number
}

export const Tabs: React.FC<TabsProps> = ({ activeTab, setActiveTab, totalCount }) => {
  return (
    <div className="flex border-b border-surface-container-high mb-6 gap-2 overflow-x-auto select-none">
      <button
        id="tab-chat"
        onClick={() => setActiveTab('chat')}
        className={`h-10 px-5 text-action-md font-medium rounded-t transition-all border-b-2 flex items-center gap-2 font-messina shrink-0 cursor-pointer ${
          activeTab === 'chat'
            ? 'border-primary text-primary bg-surface-container-lowest'
            : 'border-transparent text-text-secondary hover:text-neutral-dark hover:bg-surface-container-low'
        }`}
      >
        <Bot className="w-4 h-4" /> Ask Memory Agent
      </button>

      <button
        id="tab-gallery"
        onClick={() => setActiveTab('gallery')}
        className={`h-10 px-5 text-action-md font-medium rounded-t transition-all border-b-2 flex items-center gap-2 font-messina shrink-0 cursor-pointer ${
          activeTab === 'gallery'
            ? 'border-primary text-primary bg-surface-container-lowest'
            : 'border-transparent text-text-secondary hover:text-neutral-dark hover:bg-surface-container-low'
        }`}
      >
        <ImageIcon className="w-4 h-4" /> Screenshot Library {totalCount > 0 && `(${totalCount})`}
      </button>

      <button
        id="tab-projects"
        onClick={() => setActiveTab('projects')}
        className={`h-10 px-5 text-action-md font-medium rounded-t transition-all border-b-2 flex items-center gap-2 font-messina shrink-0 cursor-pointer ${
          activeTab === 'projects'
            ? 'border-primary text-primary bg-surface-container-lowest'
            : 'border-transparent text-text-secondary hover:text-neutral-dark hover:bg-surface-container-low'
        }`}
      >
        <FileText className="w-4 h-4" /> Project Mapping
      </button>

      <button
        id="tab-pipeline"
        onClick={() => setActiveTab('pipeline')}
        className={`h-10 px-5 text-action-md font-medium rounded-t transition-all border-b-2 flex items-center gap-2 font-messina shrink-0 cursor-pointer ${
          activeTab === 'pipeline'
            ? 'border-primary text-primary bg-surface-container-lowest'
            : 'border-transparent text-text-secondary hover:text-neutral-dark hover:bg-surface-container-low'
        }`}
      >
        <Activity className="w-4 h-4" /> System Pipeline
      </button>

      <button
        id="tab-settings"
        onClick={() => setActiveTab('settings')}
        className={`h-10 px-5 text-action-md font-medium rounded-t transition-all border-b-2 flex items-center gap-2 font-messina shrink-0 cursor-pointer ${
          activeTab === 'settings'
            ? 'border-primary text-primary bg-surface-container-lowest'
            : 'border-transparent text-text-secondary hover:text-neutral-dark hover:bg-surface-container-low'
        }`}
      >
        <Settings className="w-4 h-4" /> Settings
      </button>
    </div>
  )
}
