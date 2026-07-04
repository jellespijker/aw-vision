import React from 'react'
import { Sparkles } from 'lucide-react'

/**
 * Bayesian project-likelihood bars (top 3), learned from the user's labeled
 * history. `likelihoods` is the persisted JSON string {project: probability}.
 */
export const LikelihoodBars: React.FC<{ likelihoods?: string | null }> = ({ likelihoods }) => {
  if (!likelihoods) return null
  let probs: [string, number][] = []
  try {
    probs = Object.entries(JSON.parse(likelihoods) as Record<string, number>)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
  } catch {
    return null
  }
  if (!probs.length) return null
  return (
    <div className="bg-surface-container-low p-4 rounded border border-surface-container-high space-y-2">
      <h3 className="text-[10px] font-semibold uppercase tracking-wider text-text-secondary flex items-center gap-1.5 font-messina">
        <Sparkles className="w-4 h-4 text-primary" /> Project Likelihoods (from your history)
      </h3>
      <div className="space-y-1.5">
        {probs.map(([proj, prob]) => (
          <div key={proj} className="flex items-center gap-2 text-technical-sm font-mono">
            <span className="w-56 truncate text-neutral-dark" title={proj}>
              {proj}
            </span>
            <div className="flex-1 h-2 rounded bg-surface-container-lowest border border-surface-container overflow-hidden">
              <div className="h-full bg-primary/70" style={{ width: `${Math.round(prob * 100)}%` }}></div>
            </div>
            <span className="w-10 text-right text-text-secondary">{Math.round(prob * 100)}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}
