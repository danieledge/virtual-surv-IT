import type { CSSProperties } from 'react'
import type { CcEngagement, CcEvent } from '../../lib/commandCentre/types'
import { formatClock } from '../../lib/commandCentre/timelineLayout'
import { EVENT_TYPE_META, toneVar } from './ccVisuals'
import { EventTypeIcon } from './ccIcons'

export interface EngagementPulseMobileListProps {
  engagement: CcEngagement
  notable: CcEvent[]
  selectedEventId: string | null
  onSelectEvent: (id: string) => void
  currentTime: number
  hasStarted: boolean
}

// Phone counterpart to the horizontal pulse strip - same notable-events-only set, one row each,
// no horizontal scroll (2026-08-09 live feedback). Lighter than AgentTimelineMobileList's rows
// since Pulse is already the fast-scan/notable-only view, not the full event log.
export function EngagementPulseMobileList({
  engagement,
  notable,
  selectedEventId,
  onSelectEvent,
  currentTime,
  hasStarted,
}: EngagementPulseMobileListProps) {
  const agentById = new Map(engagement.agents.map((a) => [a.id, a]))

  return (
    <ol className="cc-pulse-mobile-list">
      {notable.map((event) => {
        const meta = EVENT_TYPE_META[event.type]
        const agent = agentById.get(event.agentId)
        const occurred = !hasStarted || event.startedAt <= currentTime
        const isSelected = event.id === selectedEventId
        return (
          <li key={event.id}>
            <button
              type="button"
              className={`cc-pulse-mobile-row${occurred ? '' : ' cc-pulse-mobile-row-pending'}${isSelected ? ' is-selected' : ''}`}
              style={{ '--tone': toneVar(meta.tone) } as CSSProperties}
              onClick={() => onSelectEvent(event.id)}
            >
              <span className="cc-pulse-mobile-icon" aria-hidden="true">
                <EventTypeIcon type={event.type} className="cc-pulse-mobile-icon-glyph" />
              </span>
              <span className="cc-pulse-mobile-body">
                <span className="cc-pulse-mobile-meta">
                  {formatClock(engagement.startClock, event.startedAt)} · {meta.label}
                </span>
                <span className="cc-pulse-mobile-title">{event.title}</span>
                <span className="cc-pulse-mobile-agent">{agent?.name ?? event.agentId}</span>
              </span>
            </button>
          </li>
        )
      })}
    </ol>
  )
}
