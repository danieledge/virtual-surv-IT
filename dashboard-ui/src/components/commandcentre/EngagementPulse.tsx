import { useRef, type CSSProperties } from 'react'
import type { CcEngagement } from '../../lib/commandCentre/types'
import { formatClock, formatElapsed } from '../../lib/commandCentre/timelineLayout'
import { EVENT_TYPE_META, PULSE_EVENT_TYPES, toneVar } from './ccVisuals'
import { EventTypeIcon } from './ccIcons'
import { CcCollapsible } from './CcCollapsible'
import { CcScrollNav } from './CcScrollNav'
import { EngagementPulseMobileList } from './EngagementPulseMobileList'

export interface EngagementPulseProps {
  engagement: CcEngagement
  selectedEventId: string | null
  onSelectEvent: (id: string) => void
  currentTime: number
}

// Fast-scan overview strip: only the notable event types (see PULSE_EVENT_TYPES), never the
// routine tool_call/spawned/started noise - the hero AgentTimeline below is where that detail
// lives.
export function EngagementPulse({ engagement, selectedEventId, onSelectEvent, currentTime }: EngagementPulseProps) {
  const notable = engagement.events.filter((e) => PULSE_EVENT_TYPES.has(e.type))
  const hasStarted = currentTime > 0
  const agentById = new Map(engagement.agents.map((a) => [a.id, a]))
  const scrollRef = useRef<HTMLDivElement>(null)
  const trackWidth = Math.max(notable.length * 70, 220)
  // Each marker's pixel offset within the track - CcScrollNav's Prev/Next jump targets, same
  // coordinate space as the scroll container's scrollLeft.
  const stops = notable.map((_, i) => (notable.length > 1 ? (i / (notable.length - 1)) * trackWidth : 0))
  const totalCost = engagement.events.reduce((sum, e) => sum + (e.cost ?? 0), 0)

  return (
    <CcCollapsible
      className="cc-pulse"
      ariaLabel="Engagement pulse"
      title="Engagement Pulse"
      peek={
        <>
          {formatElapsed(engagement.durationSeconds)} · {engagement.agents.length} agents · ${totalCost.toFixed(2)}
        </>
      }
    >
      {/* Desktop/tablet: the horizontal strip, zoom controls (visual-only, see below) and
          CcScrollNav. Phone: a vertical list instead (EngagementPulseMobileList) - no
          horizontal scroll at all, same .cc-pulse-desktop/.cc-pulse-mobile CSS-only breakpoint
          swap AgentTimeline uses. */}
      <div className="cc-pulse-desktop">
      <div className="cc-pulse-header">
        <span className="cc-info-glyph" title="Notable events only - discoveries, handoffs, loops, decisions, human touch-points and errors.">
          i
        </span>
        {/* Zoom controls (dead, always-disabled) removed 2026-08-09 - never wired to
            AgentTimeline's pxPerSecond scale and had no path to becoming real; a permanently
            inert control reads as broken, not "future work", so it's gone rather than kept as
            decoration. CcScrollNav below still gives real prev/next navigation. */}
      </div>

      <CcScrollNav scrollRef={scrollRef} stops={stops} label="pulse" />

      {/* Wrapped in a horizontally-scrollable container with a computed min-width (~4.4rem per
          marker) - same honest "scrolls inside its own contained box" pattern the hero
          AgentTimeline already uses, so at phone widths (375px) the notable-event captions get
          guaranteed breathing room instead of visually colliding, rather than being silently
          clipped or overlapped. Percentage-based marker positions below are relative to this
          track's own (now guaranteed-minimum) width, so they still work unchanged. */}
      <div className="cc-pulse-track-scroll" ref={scrollRef}>
        <div className="cc-pulse-track" style={{ minWidth: `${trackWidth}px` }}>
          {/* Stops are spaced ORDINALLY (evenly by index), not proportionally to real elapsed
              time - several notable events cluster close together in time (a handoff immediately
              followed by the loop it triggers, for instance), and time-proportional spacing
              crushed their captions into each other. Same reasoning this dashboard already
              applies to the main swimlane timeline's day axis, applied here to seconds instead of
              days. The connecting segments/markers below share one `pct` step so they stay in
              sync. */}
          {notable.slice(0, -1).map((event, i) => {
            const step = notable.length > 1 ? 100 / (notable.length - 1) : 0
            const fromPct = i * step
            const toPct = (i + 1) * step
            return (
              <span
                key={`seg-${event.id}`}
                className={`cc-pulse-segment ${i % 2 === 0 ? 'is-solid' : 'is-light'}`}
                style={{ left: `${fromPct}%`, width: `${Math.max(toPct - fromPct, 0)}%` }}
                aria-hidden="true"
              />
            )
          })}
          {notable.map((event, i) => {
            const meta = EVENT_TYPE_META[event.type]
            const agent = agentById.get(event.agentId)
            const pct = notable.length > 1 ? (i / (notable.length - 1)) * 100 : 0
            const occurred = !hasStarted || event.startedAt <= currentTime
            const isSelected = event.id === selectedEventId
            return (
              <div
                key={event.id}
                className="cc-pulse-marker-group"
                style={{ left: `${pct}%`, '--tone': toneVar(meta.tone) } as CSSProperties}
              >
                <button
                  type="button"
                  className={[
                    'cc-pulse-marker',
                    occurred ? '' : 'cc-pulse-marker-pending',
                    isSelected ? 'is-selected' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  onClick={() => onSelectEvent(event.id)}
                  aria-label={`${formatClock(engagement.startClock, event.startedAt)} — ${meta.label}: ${event.title}, ${agent?.name ?? event.agentId}`}
                >
                  <EventTypeIcon type={event.type} className="cc-pulse-marker-icon" />
                  <span className="cc-pulse-tooltip">
                    <span className="cc-pulse-tooltip-time">{formatClock(engagement.startClock, event.startedAt)}</span>
                    <span className="cc-pulse-tooltip-type">{meta.label}</span>
                    <span className="cc-pulse-tooltip-agent">{agent?.name ?? event.agentId}</span>
                    <span className="cc-pulse-tooltip-summary">{event.summary}</span>
                  </span>
                </button>
                <span className="cc-pulse-caption">{meta.label}</span>
              </div>
            )
          })}
        </div>
      </div>
      </div>

      <div className="cc-pulse-mobile">
        <EngagementPulseMobileList
          engagement={engagement}
          notable={notable}
          selectedEventId={selectedEventId}
          onSelectEvent={onSelectEvent}
          currentTime={currentTime}
          hasStarted={hasStarted}
        />
      </div>
    </CcCollapsible>
  )
}
