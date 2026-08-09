import type { CcEngagement, CcEventType } from '../../lib/commandCentre/types'
import { CcCollapsible } from './CcCollapsible'

export interface EngagementStatePanelProps {
  engagement: CcEngagement
  onSelectEventType?: (type: CcEventType) => void
}

interface StateRow {
  label: string
  value: number
  type?: CcEventType
}

// Compact counters, every one computed from engagement.events/loops - never hardcoded. Rows
// that map onto a real CcEventType become real buttons when onSelectEventType is wired up
// (future filtering hook); "Agents involved" has no matching event type, so it stays a plain
// row.
export function EngagementStatePanel({ engagement, onSelectEventType }: EngagementStatePanelProps) {
  const countByType = (type: CcEventType) => engagement.events.filter((e) => e.type === type).length

  const rows: StateRow[] = [
    { label: 'Agents involved', value: engagement.agents.length },
    { label: 'Discoveries', value: countByType('discovery'), type: 'discovery' },
    { label: 'Loops', value: engagement.loops.length, type: 'loop' },
    { label: 'Human interventions', value: countByType('human'), type: 'human' },
    { label: 'Decisions', value: countByType('decision'), type: 'decision' },
    { label: 'Errors', value: countByType('error'), type: 'error' },
  ]

  const loops = engagement.loops.length
  const errors = countByType('error')

  return (
    <CcCollapsible
      ariaLabel="Engagement state"
      title="Engagement State"
      peek={
        <>
          {loops} loop{loops === 1 ? '' : 's'} · {errors} error{errors === 1 ? '' : 's'}
        </>
      }
    >
      <div className="cc-state-grid">
        {rows.map((row) => {
          const type = row.type
          if (type && onSelectEventType) {
            return (
              <button
                key={row.label}
                type="button"
                className="cc-state-row cc-state-row-button"
                onClick={() => onSelectEventType(type)}
              >
                <span className="cc-state-value">{row.value}</span>
                <span className="cc-state-label">{row.label}</span>
              </button>
            )
          }
          return (
            <div className="cc-state-row" key={row.label}>
              <span className="cc-state-value">{row.value}</span>
              <span className="cc-state-label">{row.label}</span>
            </div>
          )
        })}
      </div>
    </CcCollapsible>
  )
}
