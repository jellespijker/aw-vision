import React from 'react'
import { Save, FileText } from 'lucide-react'
import type { Project } from '../types'

interface ProjectsTabProps {
  projectsList: Project[]
  projectsJsonInput: string
  setProjectsJsonInput: (val: string) => void
  saveProjectsJson: () => void
  savingProjects: boolean
}

export const ProjectsTab: React.FC<ProjectsTabProps> = ({
  projectsList,
  projectsJsonInput,
  setProjectsJsonInput,
  saveProjectsJson,
  savingProjects
}) => {
  const getProgressPercent = (hours: number) => {
    if (!hours) return 0
    const maxTracked = Math.max(...projectsList.map((p) => p.tracked_hours || 0), 10)
    return Math.min(100, (hours / maxTracked) * 100)
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 font-sans">
      {/* Tracked Project Listing */}
      <div className="lg:col-span-2 bg-surface-container-lowest border border-surface-container-high p-6 rounded-lg h-fit space-y-4">
        <div>
          <h3 className="font-semibold text-headline-sm text-neutral-dark">
            Tracked Hours by Project Guidelines
          </h3>
          <p className="text-text-secondary text-body-sm mt-1">
            Durations are compiled automatically by scanning screenshots, window focus records, and
            evaluating match criteria.
          </p>
        </div>

        {projectsList.length === 0 ? (
          <p className="text-text-secondary text-body-sm">No active guidelines defined.</p>
        ) : (
          <div className="space-y-4 pt-2">
            {projectsList.map((proj) => (
              <div
                key={proj.project_number}
                className="p-4 bg-surface-container-low rounded border border-surface-container-high hover:bg-surface-container transition-colors space-y-3"
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <span className="bg-primary text-on-primary text-technical-sm font-semibold px-3 py-1 rounded">
                      {proj.project_number}
                    </span>
                    <strong className="text-neutral-dark text-headline-sm">{proj.description}</strong>
                  </div>
                  {/* Noto Sans display font for tracked hours */}
                  <span className="text-display-progress text-primary font-noto tracking-tight">
                    {proj.tracked_hours || 0} h
                  </span>
                </div>

                <p className="text-text-secondary text-body-sm leading-relaxed">
                  {proj.work_entailment}
                </p>

                <div className="space-y-1">
                  <div className="w-full h-2 bg-surface-container rounded-full overflow-hidden">
                    <div
                      className="h-full bg-primary rounded-full transition-all duration-500"
                      style={{ width: `${getProgressPercent(proj.tracked_hours)}%` }}
                    ></div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Configuration JSON Editor */}
      <div className="bg-surface-container-lowest border border-surface-container-high p-5 rounded-lg h-fit space-y-4">
        <div>
          <h3 className="font-semibold text-headline-sm text-neutral-dark flex items-center gap-2">
            <FileText className="w-4 h-4 text-primary" /> Configure Guidelines
          </h3>
          <p className="text-text-secondary text-body-sm mt-1 leading-relaxed">
            Define project guidelines as JSON. This criteria dictates how the LLM vision system
            automatically categorizes and segments newly indexed screenshots.
          </p>
        </div>

        <textarea
          value={projectsJsonInput}
          onChange={(e) => setProjectsJsonInput(e.target.value)}
          rows={12}
          className="w-full p-3 font-mono text-technical-sm text-neutral-dark bg-surface-container-low border border-surface-container-high rounded focus:outline-none focus:border-primary"
        ></textarea>

        <button
          onClick={saveProjectsJson}
          disabled={savingProjects}
          className="w-full bg-primary hover:bg-primary-container text-on-primary font-messina text-action-lg font-medium h-10 px-4 rounded flex items-center justify-center gap-2 transition-colors disabled:opacity-50 select-none cursor-pointer"
        >
          <Save className="w-4 h-4" />
          {savingProjects ? 'Saving...' : 'Save Configurations'}
        </button>
      </div>
    </div>
  )
}
