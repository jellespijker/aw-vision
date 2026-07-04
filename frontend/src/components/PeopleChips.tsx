import React from 'react'
import { User, Users } from 'lucide-react'

/** Clickable chips for the people recognized in a snapshot. */
export const PeopleChips: React.FC<{ people?: string[]; onSelect?: (name: string) => void }> = ({
  people,
  onSelect
}) => {
  if (!people || people.length === 0) return null
  return (
    <div className="bg-surface-container-low p-4 rounded border border-surface-container-high space-y-2">
      <h3 className="text-[10px] font-semibold uppercase tracking-wider text-text-secondary flex items-center gap-1.5 font-messina">
        <Users className="w-4 h-4 text-primary" /> People Involved
      </h3>
      <div className="flex flex-wrap gap-1.5">
        {people.map((name) => (
          <button
            key={name}
            type="button"
            title={`Show all moments involving ${name}`}
            onClick={() => onSelect && onSelect(name)}
            className="text-technical-sm font-semibold bg-accent-surface border border-surface-container-high text-primary px-2 py-0.5 rounded font-mono flex items-center gap-1 cursor-pointer hover:border-primary transition-colors"
          >
            <User className="w-3 h-3" /> {name}
          </button>
        ))}
      </div>
    </div>
  )
}
