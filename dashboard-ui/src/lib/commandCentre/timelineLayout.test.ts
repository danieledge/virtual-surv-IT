import { describe, expect, it } from 'vitest'
import {
  buildLanes,
  buildLoopSpans,
  buildThreadSegments,
  buildTimelineLayout,
  formatClock,
  formatElapsed,
} from './timelineLayout'
import type { CcAgent, CcEngagement, CcEvent } from './types'

function agent(id: string, overrides: Partial<CcAgent> = {}): CcAgent {
  return { id, name: id, role: 'role', status: 'completed', colorIndex: 0, ...overrides }
}

function event(id: string, overrides: Partial<CcEvent> = {}): CcEvent {
  return {
    id,
    startedAt: 0,
    completedAt: 0,
    type: 'tool_call',
    agentId: 'a1',
    title: id,
    summary: '',
    status: 'completed',
    ...overrides,
  }
}

function engagement(overrides: Partial<CcEngagement> = {}): CcEngagement {
  return {
    id: 'E',
    name: 'E',
    type: 'T',
    status: 'resolved',
    startClock: '09:00:00',
    durationSeconds: 100,
    confidence: 0.8,
    agents: [agent('a1'), agent('a2')],
    events: [],
    loops: [],
    synthetic: true,
    ...overrides,
  }
}

describe('buildLanes', () => {
  it('assigns sequential lane indices in agent-array order', () => {
    const lanes = buildLanes([agent('a1'), agent('a2'), agent('a3')], 60)
    expect(lanes.map((l) => l.agentId)).toEqual(['a1', 'a2', 'a3'])
    expect(lanes.map((l) => l.laneIndex)).toEqual([0, 1, 2])
  })

  it('centers each lane vertically within its own band', () => {
    const lanes = buildLanes([agent('a1'), agent('a2')], 60)
    expect(lanes[0]!.y).toBe(30)
    expect(lanes[1]!.y).toBe(90)
  })
})

describe('buildTimelineLayout — blocks', () => {
  it('positions a block by startedAt/duration at the given px-per-second scale', () => {
    const e = engagement({
      events: [event('ev1', { agentId: 'a1', startedAt: 10, completedAt: 30 })],
    })
    const layout = buildTimelineLayout(e, { pxPerSecond: 2, laneHeight: 60, minBlockWidth: 5 })
    const block = layout.blocks[0]!
    expect(block.x).toBe(20) // 10s * 2px
    expect(block.width).toBe(40) // 20s duration * 2px
    expect(block.laneIndex).toBe(0)
  })

  it('floors zero/near-zero duration events (decisions, flags) to minBlockWidth, never zero', () => {
    const e = engagement({
      events: [event('ev1', { agentId: 'a1', startedAt: 10, completedAt: 10 })],
    })
    const layout = buildTimelineLayout(e, { pxPerSecond: 2, laneHeight: 60, minBlockWidth: 12 })
    expect(layout.blocks[0]!.width).toBe(12)
  })

  it('drops an event whose agentId is not in the roster rather than guessing a lane', () => {
    const e = engagement({
      events: [event('ev1', { agentId: 'ghost', startedAt: 0, completedAt: 5 })],
    })
    const layout = buildTimelineLayout(e)
    expect(layout.blocks).toEqual([])
  })
})

describe('buildTimelineLayout — arcs', () => {
  it('creates an arc between the source and target agent lanes for a targeted event', () => {
    const e = engagement({
      events: [event('ev1', { agentId: 'a1', targetAgentId: 'a2', startedAt: 10, completedAt: 10, type: 'handoff' })],
    })
    const layout = buildTimelineLayout(e, { pxPerSecond: 1, laneHeight: 60, minBlockWidth: 8 })
    expect(layout.arcs).toHaveLength(1)
    const arc = layout.arcs[0]!
    expect(arc.fromLaneIndex).toBe(0)
    expect(arc.toLaneIndex).toBe(1)
    expect(arc.y1).toBe(30)
    expect(arc.y2).toBe(90)
    expect(arc.isLoop).toBe(false)
  })

  it('flags a loop-typed handoff distinctly from an ordinary handoff', () => {
    const e = engagement({
      events: [event('ev1', { agentId: 'a1', targetAgentId: 'a2', type: 'loop' })],
    })
    const layout = buildTimelineLayout(e)
    expect(layout.arcs[0]!.isLoop).toBe(true)
  })

  it('produces no arc when the event has no targetAgentId', () => {
    const e = engagement({ events: [event('ev1', { agentId: 'a1' })] })
    const layout = buildTimelineLayout(e)
    expect(layout.arcs).toEqual([])
  })

  it('drops an arc whose target agent is not in the roster', () => {
    const e = engagement({
      events: [event('ev1', { agentId: 'a1', targetAgentId: 'ghost', type: 'handoff' })],
    })
    const layout = buildTimelineLayout(e)
    expect(layout.arcs).toEqual([])
  })
})

describe('formatClock', () => {
  it('adds a relative offset in seconds to the start clock', () => {
    expect(formatClock('09:41:00', 90)).toBe('09:42:30')
  })

  it('wraps past 24 hours', () => {
    expect(formatClock('23:59:00', 120)).toBe('00:01:00')
  })

  it('returns the input unchanged for a malformed start clock rather than throwing', () => {
    expect(formatClock('not-a-clock', 90)).toBe('not-a-clock')
  })
})

describe('formatElapsed', () => {
  it('formats sub-hour durations as m:ss', () => {
    expect(formatElapsed(125)).toBe('2:05')
  })

  it('formats hour-plus durations as h:mm:ss', () => {
    expect(formatElapsed(3725)).toBe('1:02:05')
  })

  it('never goes negative for a negative input', () => {
    expect(formatElapsed(-5)).toBe('0:00')
  })

  it('switches to "Nd Hh" above 24 hours', () => {
    expect(formatElapsed(3 * 86400 + 2 * 3600)).toBe('3d 2h') // 3 days, 2 hours
  })

  it('drops to 0h when the span is a whole number of days', () => {
    expect(formatElapsed(2 * 86400)).toBe('2d 0h')
  })

  it('stays in h:mm:ss form for exactly 24 hours minus a second', () => {
    expect(formatElapsed(24 * 3600 - 1)).toBe('23:59:59')
  })

  it('switches over at exactly 24 hours', () => {
    expect(formatElapsed(24 * 3600)).toBe('1d 0h')
  })
})

describe('buildThreadSegments', () => {
  it('connects chronologically consecutive events across lanes', () => {
    const e = engagement({
      events: [
        event('ev1', { agentId: 'a1', startedAt: 0, completedAt: 10 }),
        event('ev2', { agentId: 'a2', startedAt: 20, completedAt: 30 }),
      ],
    })
    const layout = buildTimelineLayout(e, { pxPerSecond: 1, laneHeight: 60, minBlockWidth: 5 })
    const segments = buildThreadSegments(e, layout)
    expect(segments).toHaveLength(1)
    expect(segments[0]!.fromEventId).toBe('ev1')
    expect(segments[0]!.toEventId).toBe('ev2')
    expect(segments[0]!.x1).toBe(10) // fromBlock.x + fromBlock.width
    expect(segments[0]!.x2).toBe(20) // toBlock.x
  })

  it('skips a pair already joined by a bold arc landing on the same lane', () => {
    const e = engagement({
      events: [
        event('ev1', { agentId: 'a1', targetAgentId: 'a2', type: 'handoff', startedAt: 0, completedAt: 0 }),
        event('ev2', { agentId: 'a2', startedAt: 10, completedAt: 20 }),
      ],
    })
    const layout = buildTimelineLayout(e, { pxPerSecond: 1, laneHeight: 60, minBlockWidth: 5 })
    const segments = buildThreadSegments(e, layout)
    expect(segments).toEqual([])
  })

  it('flags a segment whose source event carries a conversation', () => {
    const e = engagement({
      events: [
        event('ev1', {
          agentId: 'a1',
          startedAt: 0,
          completedAt: 0,
          conversation: {
            request: { agentId: 'a1', text: 'ask', tokens: 10, cost: 0.01 },
            response: { agentId: 'a2', text: 'reply', tokens: 10, cost: 0.01 },
          },
        }),
        event('ev2', { agentId: 'a2', startedAt: 10, completedAt: 20 }),
      ],
    })
    const layout = buildTimelineLayout(e, { pxPerSecond: 1, laneHeight: 60, minBlockWidth: 5 })
    const segments = buildThreadSegments(e, layout)
    expect(segments[0]!.hasConversation).toBe(true)
  })

  it('drops a segment whose endpoint event produced no block', () => {
    const e = engagement({
      events: [
        event('ev1', { agentId: 'a1', startedAt: 0, completedAt: 0 }),
        event('ev2', { agentId: 'ghost', startedAt: 10, completedAt: 10 }),
      ],
    })
    const layout = buildTimelineLayout(e)
    const segments = buildThreadSegments(e, layout)
    expect(segments).toEqual([])
  })
})

describe('buildLoopSpans', () => {
  it('produces one indexed pixel span per loop, scaled by pxPerSecond', () => {
    const e = engagement({
      loops: [
        {
          id: 'loop-a',
          startedAt: 10,
          completedAt: 40,
          agentIds: ['a1'],
          iterations: [],
          trigger: 't',
          resolution: 'r',
          cost: 0,
          tokens: 0,
        },
        {
          id: 'loop-b',
          startedAt: 50,
          completedAt: 70,
          agentIds: ['a1'],
          iterations: [],
          trigger: 't',
          resolution: 'r',
          cost: 0,
          tokens: 0,
        },
      ],
    })
    const spans = buildLoopSpans(e, 2)
    expect(spans).toEqual([
      { loopId: 'loop-a', index: 0, x1: 20, x2: 80 },
      { loopId: 'loop-b', index: 1, x1: 100, x2: 140 },
    ])
  })

  it('returns an empty array for an engagement with no loops', () => {
    expect(buildLoopSpans(engagement({ loops: [] }), 1)).toEqual([])
  })
})
