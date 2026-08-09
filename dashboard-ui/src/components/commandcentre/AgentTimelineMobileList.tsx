import type { CcEngagement } from '../../lib/commandCentre/types'
import { formatClock, formatElapsed } from '../../lib/commandCentre/timelineLayout'
import { agentColorVar } from './ccVisuals'
import { EventTypeIcon } from './ccIcons'

export interface AgentTimelineMobileListProps {
  engagement: CcEngagement
  selectedEventId: string | null
  onSelectEvent: (id: string) => void
  onSelectLoop: (loopId: string) => void
}

// Phone counterpart to the SVG swimlane above (see .cc-timeline-desktop/.cc-timeline-mobile in
// ccStyles.css - same CSS-only dual-render swap this app already uses for the OTHER swimlane
// view, TeamSwimlaneTimeline.tsx / TimelineStackedList.tsx). A vertical spine list needs no
// horizontal scroll at all (2026-08-09 live feedback: wanted the scroll gone outright, not just
// easier) - every event, in order, one row each, tap to open the same sidebar detail the SVG
// blocks/arcs already open.
export function AgentTimelineMobileList({
  engagement,
  selectedEventId,
  onSelectEvent,
  onSelectLoop,
}: AgentTimelineMobileListProps) {
  const agentById = new Map(engagement.agents.map((a) => [a.id, a]))
  const sorted = [...engagement.events].sort((a, b) => a.startedAt - b.startedAt)

  function activate(event: (typeof sorted)[number]) {
    if (event.type === 'loop' && event.loopId) onSelectLoop(event.loopId)
    else onSelectEvent(event.id)
  }

  return (
    <ol className="cc-tl-mobile-spine">
      {sorted.map((event) => {
        const agent = agentById.get(event.agentId)
        const target = event.targetAgentId ? agentById.get(event.targetAgentId) : undefined
        const isSelected = event.id === selectedEventId
        return (
          <li key={event.id}>
            <button
              type="button"
              className={`cc-tl-mobile-row${event.type === 'loop' ? ' cc-tl-mobile-row-loop' : ''}${isSelected ? ' is-selected' : ''}`}
              onClick={() => activate(event)}
            >
              <span
                className="cc-tl-mobile-avatar"
                style={{ background: agent ? agentColorVar(agent.colorIndex) : 'var(--border-strong)' }}
                aria-hidden="true"
              >
                <EventTypeIcon type={event.type} className="cc-tl-mobile-avatar-icon" />
              </span>
              <span className="cc-tl-mobile-body">
                <span className="cc-tl-mobile-meta">
                  {formatClock(engagement.startClock, event.startedAt)} · {formatElapsed(event.completedAt - event.startedAt)}
                </span>
                <span className="cc-tl-mobile-title">{event.title}</span>
                <span className="cc-tl-mobile-agent">
                  {agent?.name ?? event.agentId}
                  {target && (
                    <>
                      {' '}
                      <span aria-hidden="true">→</span> {target.name}
                    </>
                  )}
                </span>
              </span>
            </button>
          </li>
        )
      })}
    </ol>
  )
}
