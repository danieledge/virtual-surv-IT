// Pure layout math for the Command Centre's agent swimlane timeline - deliberately
// framework-free and Vitest-covered, same discipline as lib/timelineModel.ts, but a new file
// rather than an extension of that one: the data shape here is genuinely different (concurrent
// multi-second activity spans per agent, not single dated point-events on an ordinal day axis).

import type { CcAgent, CcEngagement, CcEvent } from './types'

export interface LanePosition {
  agentId: string
  laneIndex: number
  y: number
}

export interface ActivityBlock {
  event: CcEvent
  laneIndex: number
  x: number
  width: number
  y: number
}

export interface HandoffArc {
  id: string
  event: CcEvent
  fromLaneIndex: number
  toLaneIndex: number
  x: number
  y1: number
  y2: number
  /** True for loop-typed handoffs - these get the distinct "this was a rework moment" arc
   * styling, same visual language this session's loop-treatment mockups established. */
  isLoop: boolean
}

export interface TimelineLayout {
  lanes: LanePosition[]
  blocks: ActivityBlock[]
  arcs: HandoffArc[]
  totalWidth: number
  laneHeight: number
}

export interface TimelineLayoutOptions {
  pxPerSecond: number
  laneHeight: number
  /** Point-in-time events (decisions, handoffs, loop flags with equal started/completed) would
   * render as zero-width blocks otherwise - never true, always a deliberately chosen floor. */
  minBlockWidth: number
}

export const DEFAULT_LAYOUT_OPTIONS: TimelineLayoutOptions = {
  pxPerSecond: 0.6,
  laneHeight: 64,
  minBlockWidth: 10,
}

export function buildLanes(agents: CcAgent[], laneHeight: number): LanePosition[] {
  return agents.map((a, i) => ({
    agentId: a.id,
    laneIndex: i,
    y: i * laneHeight + laneHeight / 2,
  }))
}

export function buildTimelineLayout(
  engagement: CcEngagement,
  opts: TimelineLayoutOptions = DEFAULT_LAYOUT_OPTIONS,
): TimelineLayout {
  const { pxPerSecond, laneHeight, minBlockWidth } = opts
  const lanes = buildLanes(engagement.agents, laneHeight)
  const laneIndexByAgent = new Map(lanes.map((l) => [l.agentId, l.laneIndex]))

  const blocks: ActivityBlock[] = []
  const arcs: HandoffArc[] = []

  for (const event of engagement.events) {
    const laneIndex = laneIndexByAgent.get(event.agentId)
    // An event naming an agent not in the roster gets no block/arc - never guessed onto a
    // lane that doesn't exist. (Not expected from the fixture; defensive for a future real
    // data adapter that might not perfectly cross-reference.)
    if (laneIndex === undefined) continue

    const x = event.startedAt * pxPerSecond
    const rawWidth = (event.completedAt - event.startedAt) * pxPerSecond
    const width = Math.max(rawWidth, minBlockWidth)
    const y = laneIndex * laneHeight + laneHeight / 2
    blocks.push({ event, laneIndex, x, width, y })

    if (event.targetAgentId) {
      const toLaneIndex = laneIndexByAgent.get(event.targetAgentId)
      if (toLaneIndex !== undefined) {
        arcs.push({
          id: `arc-${event.id}`,
          event,
          fromLaneIndex: laneIndex,
          toLaneIndex,
          x,
          y1: y,
          y2: toLaneIndex * laneHeight + laneHeight / 2,
          isLoop: event.type === 'loop',
        })
      }
    }
  }

  const totalWidth = Math.max(
    engagement.durationSeconds * pxPerSecond + 40, // trailing margin so the last block/arc isn't flush against the edge
    200,
  )

  return { lanes, blocks, arcs, totalWidth, laneHeight }
}

export interface ThreadSegment {
  id: string
  fromEventId: string
  toEventId: string
  x1: number
  y1: number
  x2: number
  y2: number
  /** True when the *source* event of this segment has a recorded conversation - the signal an
   * envelope-icon junction glyph is drawn from, never a guess from the summary text. */
  hasConversation: boolean
}

/** Light "thread" connectors between chronologically consecutive events, skipping any pair
 * already joined by a bold handoff/loop arc (buildTimelineLayout's `arcs`) so the two visual
 * treatments never duplicate the same path - threads are the general narrative flow of the
 * investigation; arcs stay reserved for explicit handoff/loop/decision events with a
 * targetAgentId, exactly as they already render today. */
export function buildThreadSegments(engagement: CcEngagement, layout: TimelineLayout): ThreadSegment[] {
  const blockByEventId = new Map(layout.blocks.map((b) => [b.event.id, b]))
  const arcByEventId = new Map(layout.arcs.map((a) => [a.event.id, a]))
  const sorted = [...engagement.events].sort((a, b) => a.startedAt - b.startedAt)

  const segments: ThreadSegment[] = []
  for (let i = 0; i < sorted.length - 1; i++) {
    const from = sorted[i]!
    const to = sorted[i + 1]!
    const fromBlock = blockByEventId.get(from.id)
    const toBlock = blockByEventId.get(to.id)
    if (!fromBlock || !toBlock) continue

    // Already connected by a bold arc landing on the same lane - don't draw a second line on
    // top of it.
    const arc = arcByEventId.get(from.id)
    if (arc && arc.toLaneIndex === toBlock.laneIndex) continue

    segments.push({
      id: `thread-${from.id}-${to.id}`,
      fromEventId: from.id,
      toEventId: to.id,
      x1: fromBlock.x + fromBlock.width,
      y1: fromBlock.y,
      x2: toBlock.x,
      y2: toBlock.y,
      hasConversation: from.conversation !== undefined,
    })
  }
  return segments
}

export interface LoopSpan {
  loopId: string
  /** 0-based position in engagement.loops - drives the "LOOP #1" / "LOOP #2" bracket label. */
  index: number
  x1: number
  x2: number
}

/** Pixel x-span for each engagement loop's bracket label under the hero timeline, in the same
 * pxPerSecond scale as buildTimelineLayout. A separate small helper rather than folding into
 * buildTimelineLayout because loops are a flat top-level list on CcEngagement, not something
 * the per-event pass there naturally produces. */
export function buildLoopSpans(engagement: CcEngagement, pxPerSecond: number): LoopSpan[] {
  return engagement.loops.map((loop, index) => ({
    loopId: loop.id,
    index,
    x1: loop.startedAt * pxPerSecond,
    x2: loop.completedAt * pxPerSecond,
  }))
}

/** `engagement.startClock` ("HH:MM:SS") plus a relative event offset in seconds, wrapped at
 * 24h - a display formatter, never a real Date (there is no real "now" for a fixture). */
export function formatClock(startClock: string, offsetSeconds: number): string {
  const parts = startClock.split(':').map(Number)
  const [h, m, s] = parts
  if (parts.length !== 3 || [h, m, s].some((n) => Number.isNaN(n))) return startClock
  const totalStart = h! * 3600 + m! * 60 + s!
  const total = ((totalStart + Math.floor(offsetSeconds)) % 86400 + 86400) % 86400
  const hh = Math.floor(total / 3600)
  const mm = Math.floor((total % 3600) / 60)
  const ss = total % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(hh)}:${pad(mm)}:${pad(ss)}`
}

/** mm:ss (or h:mm:ss past an hour, or "Nd Hh" past 24h) duration formatter for elapsed-time /
 * loop-duration display. The fixture never produced a span past a few hours, but a real
 * engagement (day-granular real data, see fromReal.ts) routinely spans several days - rendering
 * that as e.g. "72:00:00" is technically correct but reads as broken, so above 24h this switches
 * to a coarser "Nd Hh" format (whole days + remaining whole hours, minutes/seconds dropped -
 * they're not meaningful at this scale for data that's day-granular to begin with). */
export function formatElapsed(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  if (h >= 24) {
    const days = Math.floor(h / 24)
    const remHours = h % 24
    return `${days}d ${remHours}h`
  }
  return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`
}
