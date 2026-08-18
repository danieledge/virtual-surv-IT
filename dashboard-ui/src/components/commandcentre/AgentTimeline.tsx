import { useMemo, useRef } from 'react'
import type { CSSProperties } from 'react'
import type { CcEngagement } from '../../lib/commandCentre/types'
import {
  buildLoopSpans,
  buildThreadSegments,
  buildTimelineLayout,
  DEFAULT_LAYOUT_OPTIONS,
  formatClock,
  formatElapsed,
} from '../../lib/commandCentre/timelineLayout'
import type { HandoffArc } from '../../lib/commandCentre/timelineLayout'
import { agentColorVar } from './ccVisuals'
import { CcCollapsible } from './CcCollapsible'
import { CcScrollNav } from './CcScrollNav'
import { AgentTimelineMobileList } from './AgentTimelineMobileList'

export interface AgentTimelineProps {
  engagement: CcEngagement
  selectedEventId: string | null
  onSelectEvent: (id: string) => void
  onSelectLoop: (loopId: string) => void
  currentTime: number
}

const RULER_HEIGHT = 32
const BLOCK_HEIGHT = 34
const LABEL_WIDTH = 196
const LOOP_BRACKET_HEIGHT = 26
// Text/badge rendered inside a block only above this width - below it there's no room for
// anything readable, so the block stays a plain color chip (same as before this pass).
const MIN_WIDTH_FOR_LABEL = 42
const MIN_WIDTH_FOR_BADGE = 62
const NICE_TICKS = [15, 30, 60, 120, 300, 600, 900]

function pickTickInterval(pxPerSecond: number): number {
  const targetPxGap = 90
  const rawInterval = targetPxGap / pxPerSecond
  return NICE_TICKS.find((n) => n >= rawInterval) ?? NICE_TICKS[NICE_TICKS.length - 1]!
}

// The hero view. SVG lanes (one per agent, in roster order) + activity blocks + handoff/loop
// arcs, all positioned by the pure layout math in lib/commandCentre/timelineLayout.ts. Showing
// the loop clearly - the glowing dashed amber arc with an arrowhead - is the single most
// important interaction here, so loop arcs get materially more visual weight than ordinary
// handoff arcs, never just a color swap.
export function AgentTimeline({
  engagement,
  selectedEventId,
  onSelectEvent,
  onSelectLoop,
  currentTime,
}: AgentTimelineProps) {
  const layout = useMemo(() => buildTimelineLayout(engagement), [engagement])
  const { pxPerSecond } = DEFAULT_LAYOUT_OPTIONS
  const agentById = useMemo(() => new Map(engagement.agents.map((a) => [a.id, a])), [engagement.agents])
  const eventById = useMemo(() => new Map(engagement.events.map((e) => [e.id, e])), [engagement.events])
  const threads = useMemo(() => buildThreadSegments(engagement, layout), [engagement, layout])
  const loopSpans = useMemo(() => buildLoopSpans(engagement, pxPerSecond), [engagement, pxPerSecond])
  const scrollRef = useRef<HTMLDivElement>(null)
  // One jump-stop per activity block, sorted/deduped by x - lets CcScrollNav's Prev/Next land
  // on each block's left edge, same coordinate space as the SVG (and the scroll container's
  // scrollLeft, since the SVG is the container's only child).
  const stops = useMemo(() => [...new Set(layout.blocks.map((b) => b.x))].sort((a, b) => a - b), [layout.blocks])

  const width = layout.totalWidth
  const laneAreaHeight = layout.lanes.length * layout.laneHeight
  const bracketSpace = loopSpans.length > 0 ? LOOP_BRACKET_HEIGHT : 0
  const height = RULER_HEIGHT + laneAreaHeight + bracketSpace
  const hasStarted = currentTime > 0
  const cursorX = Math.min(currentTime, engagement.durationSeconds) * pxPerSecond
  const cursorPillX = Math.min(Math.max(cursorX, 28), Math.max(width - 28, 28))

  const tickInterval = pickTickInterval(pxPerSecond)
  const ticks: number[] = []
  for (let t = 0; t <= engagement.durationSeconds; t += tickInterval) ticks.push(t)

  function handleArcActivate(arc: HandoffArc) {
    if (arc.isLoop && arc.event.loopId) {
      onSelectLoop(arc.event.loopId)
    } else {
      onSelectEvent(arc.event.id)
    }
  }

  return (
    <CcCollapsible
      className="cc-timeline-panel"
      ariaLabel="Agent activity timeline"
      title="Agent Timeline"
      peek={
        <>
          {layout.blocks.length} activity blocks · {formatElapsed(engagement.durationSeconds)}
        </>
      }
    >
      {/* Desktop/tablet: the SVG swimlane canvas, horizontally scrollable (CcScrollNav) when it
          overflows. Phone: a vertical spine list instead (AgentTimelineMobileList) - the
          .cc-timeline-desktop/.cc-timeline-mobile pair is a pure CSS breakpoint swap, same
          pattern as .timeline-desktop/.timeline-mobile elsewhere in this app (both render
          unconditionally; no JS matchMedia, no first-paint flicker). CcScrollNav is
          desktop-only now - the mobile list needs no horizontal scroll at all. */}
      <div className="cc-timeline-desktop">
        <CcScrollNav scrollRef={scrollRef} stops={stops} label="timeline" />
        <div className="cc-timeline">
        <div className="cc-timeline-labels" style={{ width: LABEL_WIDTH }}>
          <div className="cc-timeline-label-spacer" style={{ height: RULER_HEIGHT }} />
          {layout.lanes.map((lane) => {
            const agent = agentById.get(lane.agentId)
            if (!agent) return null
            return (
              <div className="cc-timeline-label-row" key={lane.agentId} style={{ height: layout.laneHeight }}>
                <span
                  className="cc-lane-dot"
                  style={{ background: agentColorVar(agent.colorIndex) }}
                  aria-hidden="true"
                />
                <span className="cc-timeline-label-text">
                  <span className="cc-timeline-label-name">{agent.name}</span>
                  <span className="cc-timeline-label-role">{agent.role}</span>
                </span>
              </div>
            )
          })}
        </div>

        <div className="cc-timeline-scroll" ref={scrollRef}>
          <svg
            width={width}
            height={height}
            role="img"
            aria-label="Agent swimlane timeline with handoff and loop arcs"
          >
            <defs>
              <marker
                id="cc-arrow-handoff"
                viewBox="0 0 10 10"
                refX="8"
                refY="5"
                markerWidth="6"
                markerHeight="6"
                orient="auto-start-reverse"
              >
                <path d="M0,0 L10,5 L0,10 Z" fill="var(--accent)" />
              </marker>
              <marker
                id="cc-arrow-loop"
                viewBox="0 0 10 10"
                refX="8"
                refY="5"
                markerWidth="9"
                markerHeight="9"
                orient="auto-start-reverse"
              >
                <path d="M0,0 L10,5 L0,10 Z" fill="var(--warn)" />
              </marker>
            </defs>

            <g className="cc-ruler">
              {ticks.map((t) => (
                <g key={t} transform={`translate(${t * pxPerSecond},0)`}>
                  <line y1={RULER_HEIGHT - 10} y2={height} className="cc-ruler-grid" strokeWidth={1} />
                  <text x={4} y={RULER_HEIGHT - 14} className="cc-ruler-label">
                    {formatClock(engagement.startClock, t)}
                  </text>
                </g>
              ))}
            </g>

            {layout.lanes.map((lane) => (
              <line
                key={lane.agentId}
                x1={0}
                x2={width}
                y1={RULER_HEIGHT + lane.y}
                y2={RULER_HEIGHT + lane.y}
                className="cc-lane-line"
                strokeWidth={1}
              />
            ))}

            {/* Light "thread" connectors between chronologically consecutive events - additive
                to the handoff/loop arcs below, never drawn over the same path (see
                buildThreadSegments). A small envelope glyph marks a junction whose source event
                carries a recorded conversation - a genuine signal, not decoration. */}
            {threads.map((thread) => {
              const sourceEvent = eventById.get(thread.fromEventId)
              const targetEvent = eventById.get(thread.toEventId)
              const occurred = !hasStarted || (targetEvent ? targetEvent.startedAt <= currentTime : true)
              const midX = (thread.x1 + thread.x2) / 2
              const midY = (thread.y1 + thread.y2) / 2 + RULER_HEIGHT
              return (
                <g key={thread.id} className={occurred ? 'cc-thread-group' : 'cc-thread-group cc-thread-group-pending'}>
                  <line
                    x1={thread.x1}
                    y1={thread.y1 + RULER_HEIGHT}
                    x2={thread.x2}
                    y2={thread.y2 + RULER_HEIGHT}
                    className="cc-thread"
                    strokeWidth={1}
                  />
                  {thread.hasConversation && sourceEvent && (
                    <g transform={`translate(${midX}, ${midY})`} className="cc-envelope-badge">
                      <title>{`Conversation recorded: ${sourceEvent.title}`}</title>
                      <circle r={7} className="cc-envelope-badge-circle" />
                      <path d="M-3.4,-2 L0,0.6 L3.4,-2 M-3.4,-2 L-3.4,2.4 L3.4,2.4 L3.4,-2" className="cc-envelope-badge-icon" />
                    </g>
                  )}
                </g>
              )
            })}

            {layout.arcs.map((arc, i) => {
              const y1 = RULER_HEIGHT + arc.y1
              const y2 = RULER_HEIGHT + arc.y2
              const bulge = arc.isLoop ? 60 : 34
              const x = arc.x
              const path = `M ${x},${y1} C ${x + bulge},${y1} ${x + bulge},${y2} ${x},${y2}`
              const occurred = !hasStarted || arc.event.startedAt <= currentTime
              const isSelected = arc.event.id === selectedEventId
              const delay = `${Math.min(i * 40, 600)}ms`
              const pathClassName = [
                'cc-arc',
                arc.isLoop ? 'cc-arc-loop' : 'cc-arc-handoff',
                isSelected ? 'is-selected' : '',
              ]
                .filter(Boolean)
                .join(' ')
              // Bezier midpoint at t=0.5 (B(0.5) = 0.125*(P0+3P1+3P2+P3)) - close enough for a
              // decorative badge anchor, doesn't need to be exact.
              const midX = 0.125 * (x + 3 * (x + bulge) + 3 * (x + bulge) + x)
              const midY = 0.125 * (y1 + 3 * y1 + 3 * y2 + y2)

              return (
                <g
                  key={arc.id}
                  className={[
                    'cc-arc-group',
                    arc.isLoop ? 'cc-arc-group-loop' : 'cc-arc-group-handoff',
                    occurred ? '' : 'cc-arc-group-pending',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  style={{ '--delay': delay } as CSSProperties}
                >
                  <title>{arc.isLoop ? `Loop: ${arc.event.title}` : `Handoff: ${arc.event.title}`}</title>
                  {arc.isLoop && <path d={path} className="cc-arc-glow" fill="none" strokeWidth={10} />}
                  <path
                    d={path}
                    className={pathClassName}
                    fill="none"
                    strokeWidth={arc.isLoop ? 3 : 2}
                    markerEnd={arc.isLoop ? 'url(#cc-arrow-loop)' : 'url(#cc-arrow-handoff)'}
                    pathLength={arc.isLoop ? undefined : 1}
                    tabIndex={0}
                    role="button"
                    aria-label={arc.isLoop ? `Loop: ${arc.event.title}` : `Handoff: ${arc.event.title}`}
                    onClick={() => handleArcActivate(arc)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        handleArcActivate(arc)
                      }
                    }}
                  />
                  {arc.event.conversation && (
                    <g transform={`translate(${midX}, ${midY})`} className="cc-envelope-badge" aria-hidden="true">
                      <circle r={7} className="cc-envelope-badge-circle" />
                      <path d="M-3.4,-2 L0,0.6 L3.4,-2 M-3.4,-2 L-3.4,2.4 L3.4,2.4 L3.4,-2" className="cc-envelope-badge-icon" />
                    </g>
                  )}
                </g>
              )
            })}

            {layout.blocks.map((block) => {
              const agent = agentById.get(block.event.agentId)
              const occurred = !hasStarted || block.event.startedAt <= currentTime
              const isSelected = block.event.id === selectedEventId
              const showLabel = block.width >= MIN_WIDTH_FOR_LABEL
              const showBadge = block.width >= MIN_WIDTH_FOR_BADGE
              const rectY = RULER_HEIGHT + block.y - BLOCK_HEIGHT / 2
              const clipId = `cc-block-clip-${block.event.id}`
              return (
                <g
                  key={block.event.id}
                  className={occurred ? '' : 'cc-block-pending'}
                >
                  {showLabel && (
                    <clipPath id={clipId}>
                      <rect x={block.x} y={rectY} width={block.width} height={BLOCK_HEIGHT} rx={4} />
                    </clipPath>
                  )}
                  <rect
                    x={block.x}
                    y={rectY}
                    width={block.width}
                    height={BLOCK_HEIGHT}
                    rx={4}
                    className={[
                      'cc-block',
                      block.event.type === 'loop' ? 'cc-block-loop' : '',
                      isSelected ? 'is-selected' : '',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                    fill={agent ? agentColorVar(agent.colorIndex) : 'var(--border-strong)'}
                    tabIndex={0}
                    role="button"
                    aria-label={`${block.event.title} — ${agent?.name ?? block.event.agentId}, ${formatElapsed(block.event.completedAt - block.event.startedAt)}`}
                    onClick={() => onSelectEvent(block.event.id)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        onSelectEvent(block.event.id)
                      }
                    }}
                  >
                    <title>{block.event.title}</title>
                  </rect>
                  {showLabel && (
                    <g clipPath={`url(#${clipId})`} pointerEvents="none">
                      <text x={block.x + 7} y={rectY + 14} className="cc-block-title">
                        {block.event.title}
                      </text>
                      <text x={block.x + 7} y={rectY + 27} className="cc-block-duration">
                        {formatElapsed(block.event.completedAt - block.event.startedAt)}
                      </text>
                      {showBadge && (
                        <g transform={`translate(${block.x + block.width - 15}, ${rectY + 5})`} className="cc-block-badge">
                          <path d="M0,7 L7,7 L7,0 M7,7 L0,0" className="cc-block-badge-icon" />
                        </g>
                      )}
                    </g>
                  )}
                </g>
              )
            })}

            {loopSpans.map((span) => {
              const bracketY = RULER_HEIGHT + laneAreaHeight + 12
              return (
                <g key={span.loopId} className="cc-loop-bracket">
                  <line x1={span.x1} x2={span.x2} y1={bracketY} y2={bracketY} className="cc-loop-bracket-line" />
                  <line x1={span.x1} x2={span.x1} y1={bracketY - 4} y2={bracketY + 4} className="cc-loop-bracket-line" />
                  <line x1={span.x2} x2={span.x2} y1={bracketY - 4} y2={bracketY + 4} className="cc-loop-bracket-line" />
                  <text x={(span.x1 + span.x2) / 2} y={bracketY + 15} textAnchor="middle" className="cc-loop-bracket-label">
                    {`LOOP #${span.index + 1}`}
                  </text>
                </g>
              )
            })}

            <line x1={cursorX} x2={cursorX} y1={16} y2={height} className="cc-cursor" strokeWidth={2} />
            <g transform={`translate(${cursorPillX}, 0)`} className="cc-cursor-pill-group">
              <rect x={-30} y={0} width={60} height={15} rx={7.5} className="cc-cursor-pill" />
              <text x={0} y={10.5} textAnchor="middle" className="cc-cursor-pill-text">
                {formatClock(engagement.startClock, currentTime)}
              </text>
            </g>
          </svg>
        </div>
        </div>
      </div>

      <div className="cc-timeline-mobile">
        <AgentTimelineMobileList
          engagement={engagement}
          selectedEventId={selectedEventId}
          onSelectEvent={onSelectEvent}
          onSelectLoop={onSelectLoop}
        />
      </div>
    </CcCollapsible>
  )
}
