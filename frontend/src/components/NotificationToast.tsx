import React, { useEffect } from 'react'
import { CheckCircle2, AlertTriangle, X } from 'lucide-react'

interface NotificationToastProps {
  message: { text: string; type: 'success' | 'danger' } | null
  onClose: () => void
}

export const NotificationToast: React.FC<NotificationToastProps> = ({ message, onClose }) => {
  useEffect(() => {
    if (message) {
      const timer = setTimeout(() => {
        onClose()
      }, 4000)
      return () => clearTimeout(timer)
    }
  }, [message, onClose])

  if (!message) return null

  return (
    <div
      className={`fixed top-5 right-5 z-50 p-4 rounded border text-on-surface font-sans text-action-md flex items-center gap-3 animate-fade-in transition-all ${
        message.type === 'success'
          ? 'bg-surface-container border-success-green text-success-green dark:bg-surface-container-high/30 dark:border-success-green/30'
          : 'bg-danger-surface border-danger-primary text-danger-primary dark:bg-danger-primary/10 dark:border-danger-primary/30'
      }`}
      style={{
        boxShadow: 'none', // Flat model as per DESIGN.md
      }}
    >
      {message.type === 'success' ? (
        <CheckCircle2 className="w-5 h-5 text-success-green shrink-0" />
      ) : (
        <AlertTriangle className="w-5 h-5 text-danger-primary shrink-0" />
      )}
      <span className="font-medium text-neutral-dark">{message.text}</span>
      <button
        onClick={onClose}
        className="text-text-secondary hover:text-on-surface ml-2 shrink-0 transition-colors"
        aria-label="Close notification"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  )
}
