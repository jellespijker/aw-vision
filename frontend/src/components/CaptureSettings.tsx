import React from 'react'
import { Camera, Clock, ShieldAlert, RefreshCw } from 'lucide-react'

interface CaptureSettingsProps {
  settings: Record<string, any>
  handleSettingChange: (key: string, value: any) => void
}

export const CaptureSettings: React.FC<CaptureSettingsProps> = ({
  settings,
  handleSettingChange
}) => {
  return (
    <div className="bg-surface-container-lowest border border-surface-container-high p-6 rounded-lg space-y-5">
      <h3 className="font-bold text-headline-sm text-neutral-dark flex items-center gap-2 border-b border-surface-container-high pb-3">
        <Camera className="w-5 h-5 text-primary" /> Capture &amp; Retention
      </h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <label htmlFor="screenshotIntervalInput" className="text-body-sm font-semibold text-text-secondary flex items-center gap-1.5">
            <Camera className="w-3.5 h-3.5" /> Screenshot Interval (seconds)
          </label>
          <input
            id="screenshotIntervalInput"
            type="number"
            min="5"
            value={settings.screenshot_interval_seconds ?? 60}
            onChange={(e) => handleSettingChange('screenshot_interval_seconds', parseInt(e.target.value) || 0)}
            className="w-full bg-surface-container-low border border-surface-container-high h-11 px-4 rounded text-body-md text-neutral-dark outline-none focus:border-primary font-mono transition-colors"
          />
          <p className="text-[11px] text-text-secondary">How often the watcher captures the active screen.</p>
        </div>

        <div className="space-y-1.5">
          <label htmlFor="checkIntervalInput" className="text-body-sm font-semibold text-text-secondary flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5" /> Processing Check Interval (seconds)
          </label>
          <input
            id="checkIntervalInput"
            type="number"
            min="1"
            value={settings.check_interval_seconds ?? 10}
            onChange={(e) => handleSettingChange('check_interval_seconds', parseInt(e.target.value) || 0)}
            className="w-full bg-surface-container-low border border-surface-container-high h-11 px-4 rounded text-body-md text-neutral-dark outline-none focus:border-primary font-mono transition-colors"
          />
          <p className="text-[11px] text-text-secondary">How often the processor daemon scans the pending queue.</p>
        </div>

        <div className="space-y-1.5">
          <label htmlFor="lifetimeInput" className="text-body-sm font-semibold text-text-secondary flex items-center gap-1.5">
            <ShieldAlert className="w-3.5 h-3.5" /> Screenshot Retention (days)
          </label>
          <input
            id="lifetimeInput"
            type="number"
            min="1"
            value={settings.max_screenshot_lifetime_days ?? 14}
            onChange={(e) => handleSettingChange('max_screenshot_lifetime_days', parseInt(e.target.value) || 0)}
            className="w-full bg-surface-container-low border border-surface-container-high h-11 px-4 rounded text-body-md text-neutral-dark outline-none focus:border-primary font-mono transition-colors"
          />
          <p className="text-[11px] text-text-secondary">Raw screenshot files are purged after this many days.</p>
        </div>

        <div className="space-y-1.5">
          <label htmlFor="cleanupInput" className="text-body-sm font-semibold text-text-secondary flex items-center gap-1.5">
            <RefreshCw className="w-3.5 h-3.5" /> Cleanup Interval (hours)
          </label>
          <input
            id="cleanupInput"
            type="number"
            min="1"
            value={settings.cleanup_interval_hours ?? 1}
            onChange={(e) => handleSettingChange('cleanup_interval_hours', parseInt(e.target.value) || 0)}
            className="w-full bg-surface-container-low border border-surface-container-high h-11 px-4 rounded text-body-md text-neutral-dark outline-none focus:border-primary font-mono transition-colors"
          />
          <p className="text-[11px] text-text-secondary">How often the retention cleanup sweep runs.</p>
        </div>
      </div>
    </div>
  )
}
