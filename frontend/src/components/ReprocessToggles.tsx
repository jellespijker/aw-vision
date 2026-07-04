import React from 'react'

interface ReprocessTogglesProps {
  reprocessOcr: boolean
  setReprocessOcr: (val: boolean) => void
  reprocessLowConfOnly: boolean
  setReprocessLowConfOnly: (val: boolean) => void
}

/** The bulk-reprocess option checkboxes (OCR sweep, low-confidence-only). */
export const ReprocessToggles: React.FC<ReprocessTogglesProps> = ({
  reprocessOcr,
  setReprocessOcr,
  reprocessLowConfOnly,
  setReprocessLowConfOnly
}) => (
  <>
    <div className="flex items-center gap-2.5">
      <input
        type="checkbox"
        id="reprocessOcrCheckbox"
        name="reprocessOcrCheckbox"
        checked={reprocessOcr}
        onChange={(e) => setReprocessOcr(e.target.checked)}
        className="w-4 h-4 rounded border-surface-container-high text-primary focus:ring-primary cursor-pointer"
      />
      <label
        htmlFor="reprocessOcrCheckbox"
        className="text-body-sm font-medium text-neutral-dark cursor-pointer font-sans"
      >
        Include full OCR Sweep (Re-extract Text, slow)
      </label>
    </div>

    <div className="flex items-center gap-2.5">
      <input
        type="checkbox"
        id="reprocessLowConfCheckbox"
        name="reprocessLowConfCheckbox"
        checked={reprocessLowConfOnly}
        onChange={(e) => setReprocessLowConfOnly(e.target.checked)}
        className="w-4 h-4 rounded border-surface-container-high text-primary focus:ring-primary cursor-pointer"
      />
      <label
        htmlFor="reprocessLowConfCheckbox"
        className="text-body-sm font-medium text-neutral-dark cursor-pointer font-sans"
        title="Skips human-verified and direct-match snapshots; re-analyzes only unclassified, thematic and uncertain ones with everything learned since (new labels, calendar/VCS journal events, statistical likelihoods)"
      >
        Only low-confidence / unclassified (re-analyze with new insights)
      </label>
    </div>
  </>
)
