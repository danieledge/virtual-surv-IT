import { describe, expect, it } from 'vitest'
import {
  MILESTONE_LANE_KEY,
  buildTimelineModel,
  parseHandoff,
  parseLogLine,
  parseTeamMember,
} from './timelineModel'
import type { Engagement } from './types'

const ROLE_LABELS = {
  'rules-developer': 'detection rules',
  'code-reviewer': 'code review',
}

function engagement(overrides: Partial<Engagement> = {}): Engagement {
  return {
    slug: 'eng-a',
    dir: 'eng-a',
    title: 'Test engagement',
    status: 'in_progress',
    profile: 'standard',
    opened: '2026-08-01',
    closed: null,
    outstanding: 0,
    pendingRatifications: 0,
    consentOutcome: null,
    team: [],
    artifacts: [],
    settingsSnapshot: null,
    log: [],
    costRollup: null,
    ...overrides,
  }
}

describe('parseTeamMember', () => {
  it('parses a well-formed "Name (role)" entry', () => {
    const a = parseTeamMember('Mateo (rules-developer)', 0)
    expect(a.name).toBe('Mateo')
    expect(a.roleSlug).toBe('rules-developer')
    expect(a.key).toBe('0:Mateo')
    expect(a.initials).toBe('MA')
  })

  it('still returns a real actor for a malformed entry (no parens)', () => {
    const a = parseTeamMember('Just A Name', 2)
    expect(a.name).toBe('Just A Name')
    expect(a.roleSlug).toBeNull()
    expect(a.key).toBe('2:Just A Name')
  })

  it('keys two duplicate names distinctly by index', () => {
    const a = parseTeamMember('Mateo (rules-developer)', 0)
    const b = parseTeamMember('Mateo (code-reviewer)', 1)
    expect(a.key).not.toBe(b.key)
  })

  // 2026-08-09 live finding: the eval harness (scripts/eval_engage.py) writes team entries as
  // "🤖 Name, Role (Team)" - a real, different convention from "Name (role-slug)" above. Before
  // this was handled, "🤖 Ravi, Code Reviewer (Virtual Surveillance IT)" parsed as name="🤖
  // Ravi, Code Reviewer", roleSlug="Virtual Surveillance IT" - neither useful, and it broke
  // real review-loop handoffs (which reference people by slug token, e.g. "code-reviewer")
  // since nothing could ever match that roleSlug.
  it('parses the "🤖 Name, Role (Team)" convention, deriving a real slug from the role text', () => {
    const a = parseTeamMember('🤖 Ravi, Code Reviewer (Virtual Surveillance IT)', 0)
    expect(a.name).toBe('Ravi')
    expect(a.roleSlug).toBe('code-reviewer')
    expect(a.key).toBe('0:Ravi')
    expect(a.initials).toBe('RA')
  })

  it('slugifies a multi-word role consistently with scripts/dashboard.py\'s _slugify', () => {
    const a = parseTeamMember('🤖 Morgan, Project Manager (Virtual Surveillance IT)', 0)
    expect(a.name).toBe('Morgan')
    expect(a.roleSlug).toBe('project-manager')
  })

  it('handles the comma convention without the leading 🤖 too', () => {
    const a = parseTeamMember('Linh, QA Engineer (Virtual Surveillance IT)', 0)
    expect(a.name).toBe('Linh')
    expect(a.roleSlug).toBe('qa-engineer')
  })
})

describe('parseLogLine', () => {
  it('parses a tagged line', () => {
    expect(parseLogLine('2026-08-03 [review-loop]: Ravi -> Mateo: resubmit')).toEqual({
      date: '2026-08-03',
      tag: 'review-loop',
      text: 'Ravi -> Mateo: resubmit',
    })
  })

  it('parses a plain line', () => {
    expect(parseLogLine('2026-08-03: drafted v1')).toEqual({
      date: '2026-08-03',
      tag: null,
      text: 'drafted v1',
    })
  })

  it('returns null for a line matching neither shape', () => {
    expect(parseLogLine('not a log line at all')).toBeNull()
  })
})

describe('parseHandoff', () => {
  const actors = [parseTeamMember('Mateo (rules-developer)', 0), parseTeamMember('Ravi (code-reviewer)', 1)]

  it('resolves both sides by name', () => {
    const h = parseHandoff('Ravi -> Mateo: resubmit', actors)
    expect(h?.fromKey).toBe('1:Ravi')
    expect(h?.toKey).toBe('0:Mateo')
    expect(h?.reason).toBe('resubmit')
  })

  it('resolves both sides by role slug (pre-humanization log text)', () => {
    const h = parseHandoff('code-reviewer -> rules-developer: resubmit', actors)
    expect(h?.fromKey).toBe('1:Ravi')
    expect(h?.toKey).toBe('0:Mateo')
  })

  it('resolves a name with an already-humanized role suffix', () => {
    const h = parseHandoff('Ravi (code review) -> Mateo (detection rules): resubmit', actors)
    expect(h?.fromKey).toBe('1:Ravi')
    expect(h?.toKey).toBe('0:Mateo')
  })

  it('returns null keys for an unresolved name, not a thrown error', () => {
    const h = parseHandoff('Someone Else -> Mateo: resubmit', actors)
    expect(h?.fromKey).toBeNull()
    expect(h?.toKey).toBe('0:Mateo')
  })

  it('returns null entirely for text with no "->" shape', () => {
    expect(parseHandoff('approved, no changes needed', actors)).toBeNull()
  })
})

describe('buildTimelineModel', () => {
  it('places opened/artifacts/closed on the Milestones lane in order', () => {
    const model = buildTimelineModel(
      engagement({
        opened: '2026-08-01',
        closed: '2026-08-05',
        artifacts: [
          {
            path: 'spec.md',
            absPath: '/tmp/proj/artifacts/eng-a/spec.md',
            title: 'Spec',
            status: 'final',
            added: '2026-08-02',
          },
        ],
      }),
      ROLE_LABELS
    )
    expect(model.lanes[0]!.key).toBe(MILESTONE_LANE_KEY)
    const dates = model.events.map((e) => e.date)
    expect(dates).toEqual(['2026-08-01', '2026-08-02', '2026-08-05'])
    expect(model.events.every((e) => e.laneKey === MILESTONE_LANE_KEY)).toBe(true)

    const artifactEvent = model.events.find((e) => e.kind === 'artifact')!
    expect(artifactEvent.href).toBe('file:///tmp/proj/artifacts/eng-a/spec.md')
    const opened = model.events.find((e) => e.kind === 'opened')!
    const closed = model.events.find((e) => e.kind === 'closed')!
    expect(opened.href).toBeNull() // only artifact events have an underlying file
    expect(closed.href).toBeNull()
  })

  it('has no href when the artifact carries no absPath (e.g. an unreadable pack)', () => {
    const model = buildTimelineModel(
      engagement({
        opened: null,
        artifacts: [{ path: 'spec.md', absPath: null, title: 'Spec', status: 'final', added: '2026-08-02' }],
      }),
      ROLE_LABELS
    )
    expect(model.events[0]!.href).toBeNull()
  })

  it('produces exactly one arc for a fully-resolved review-loop handoff', () => {
    const model = buildTimelineModel(
      engagement({
        team: ['Mateo (rules-developer)', 'Ravi (code-reviewer)'],
        log: ['2026-08-03 [review-loop]: Ravi -> Mateo: resubmit'],
      }),
      ROLE_LABELS
    )
    expect(model.arcs).toHaveLength(1)
    expect(model.arcs[0]!.fromLaneKey).toBe('1:Ravi')
    expect(model.arcs[0]!.toLaneKey).toBe('0:Mateo')
    expect(model.arcs[0]!.selfLoop).toBe(false)
    expect(model.unresolvedTagCount).toBe(0)
    const tagged = model.events.find((e) => e.kind === 'tagged')
    expect(tagged?.loop).toBe(true)
    expect(tagged?.laneKey).toBe('1:Ravi')
  })

  it('keeps loop arcs correctly paired with their node after a date-based reorder', () => {
    // Two handoffs pushed in one order, but with dates that sort them the OTHER way -
    // regression guard for rawIndex-based (not push-order-based) arc/event pairing.
    const model = buildTimelineModel(
      engagement({
        opened: null, // avoid colliding with the default '2026-08-01' used below
        team: ['Mateo (rules-developer)', 'Ravi (code-reviewer)'],
        log: [
          '2026-08-09 [review-loop]: Ravi -> Mateo: second, later date',
          '2026-08-01 [review-loop]: Mateo -> Ravi: first, earlier date',
        ],
      }),
      ROLE_LABELS
    )
    expect(model.arcs).toHaveLength(2)
    const early = model.events.find((e) => e.date === '2026-08-01')!
    const late = model.events.find((e) => e.date === '2026-08-09')!
    expect(early.order).toBeLessThan(late.order)
    const earlyArc = model.arcs.find((a) => a.order === early.order)!
    const lateArc = model.arcs.find((a) => a.order === late.order)!
    expect(earlyArc.fromLaneKey).toBe('0:Mateo')
    expect(lateArc.fromLaneKey).toBe('1:Ravi')
  })

  it('renders a self-loop (same actor both sides) without crashing', () => {
    const model = buildTimelineModel(
      engagement({
        team: ['Mateo (rules-developer)'],
        log: ['2026-08-03 [review-loop]: Mateo -> Mateo: re-flagged own note'],
      }),
      ROLE_LABELS
    )
    expect(model.arcs).toHaveLength(1)
    expect(model.arcs[0]!.selfLoop).toBe(true)
  })

  it('flags an unresolved handoff without producing an arc', () => {
    const model = buildTimelineModel(
      engagement({
        team: ['Mateo (rules-developer)'],
        log: ['2026-08-03 [review-loop]: Someone External -> Mateo: feedback'],
      }),
      ROLE_LABELS
    )
    expect(model.arcs).toHaveLength(0)
    expect(model.unresolvedTagCount).toBe(1)
    const tagged = model.events.find((e) => e.kind === 'tagged')
    expect(tagged?.loop).toBe(true)
    expect(tagged?.laneKey).toBe('0:Mateo') // the one side that DID resolve
  })

  it('handles an empty team - every log entry lands on Milestones, no arcs', () => {
    const model = buildTimelineModel(
      engagement({
        team: [],
        log: ['2026-08-03 [review-loop]: Ravi -> Mateo: resubmit', '2026-08-04: a plain note'],
      }),
      ROLE_LABELS
    )
    expect(model.lanes).toHaveLength(1)
    expect(model.arcs).toHaveLength(0)
    expect(model.events.every((e) => e.laneKey === MILESTONE_LANE_KEY)).toBe(true)
  })

  it('handles an empty log - opened/closed still render, team lanes still exist', () => {
    const model = buildTimelineModel(
      engagement({
        team: ['Mateo (rules-developer)'],
        log: [],
        opened: '2026-08-01',
        closed: '2026-08-02',
      }),
      ROLE_LABELS
    )
    expect(model.lanes).toHaveLength(2) // Milestones + Mateo, even with zero activity
    expect(model.events.map((e) => e.kind)).toEqual(['opened', 'closed'])
  })

  it('never throws on a log line with an invalid calendar date', () => {
    const model = buildTimelineModel(
      engagement({ opened: null, log: ['2026-02-30: impossible date'] }),
      ROLE_LABELS
    )
    expect(model.unparsableDateCount).toBe(1)
    expect(model.events).toHaveLength(1) // still gets a slot, not silently dropped
  })

  it('falls back to Milestones for an ambiguous plain-note first-name match', () => {
    const model = buildTimelineModel(
      engagement({
        team: ['Mateo (rules-developer)', 'Mateo (code-reviewer)'],
        log: ['2026-08-03: Mateo left a note'],
      }),
      ROLE_LABELS
    )
    const note = model.events.find((e) => e.kind === 'note')!
    expect(note.laneKey).toBe(MILESTONE_LANE_KEY) // ambiguous - two Mateos - never guesses
  })

  it('unambiguous plain-note first-name match lands in that actor\'s lane', () => {
    const model = buildTimelineModel(
      engagement({
        team: ['Mateo (rules-developer)', 'Ravi (code-reviewer)'],
        log: ['2026-08-03: Mateo drafted v1'],
      }),
      ROLE_LABELS
    )
    const note = model.events.find((e) => e.kind === 'note')!
    expect(note.laneKey).toBe('0:Mateo')
  })
})
