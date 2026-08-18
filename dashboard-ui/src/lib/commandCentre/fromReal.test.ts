import { describe, expect, it } from 'vitest'
import { buildCcEngagementFromReal } from './fromReal'
import type { Engagement } from '../types'

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

describe('buildCcEngagementFromReal - top-level fields', () => {
  it('composes id from project name + slug, name from title, type from profile', () => {
    const cc = buildCcEngagementFromReal(engagement({ slug: 'eng-a', title: 'Cross-Venue Review' }), 'proj-x', ROLE_LABELS)
    expect(cc.id).toBe('proj-x/eng-a')
    expect(cc.name).toBe('Cross-Venue Review')
    expect(cc.type).toBe('standard')
  })

  it('falls back to slug for name when title is null, and a generic type when profile is null', () => {
    const cc = buildCcEngagementFromReal(engagement({ title: null, profile: null, slug: 'eng-b' }), 'proj-x', ROLE_LABELS)
    expect(cc.name).toBe('eng-b')
    expect(cc.type).toBe('Engagement')
  })

  it('is always synthetic: false and omits confidence entirely', () => {
    const cc = buildCcEngagementFromReal(engagement(), 'proj-x', ROLE_LABELS)
    expect(cc.synthetic).toBe(false)
    expect(cc.confidence).toBeUndefined()
  })

  it.each([
    ['in_progress', 'investigating'],
    ['closing', 'investigating'],
    ['blocked', 'blocked'],
    ['closed', 'resolved'],
    ['invalid', 'blocked'],
  ] as const)('maps Engagement.status %s -> CcEngagement.status %s', (real, expected) => {
    const cc = buildCcEngagementFromReal(engagement({ status: real }), 'proj-x', ROLE_LABELS)
    expect(cc.status).toBe(expected)
  })
})

describe('buildCcEngagementFromReal - agents', () => {
  it('produces one CcAgent per team actor, with humanized role, stable colorIndex, status completed', () => {
    const cc = buildCcEngagementFromReal(
      engagement({ team: ['Mateo (rules-developer)', 'Ravi (code-reviewer)'] }),
      'proj-x',
      ROLE_LABELS,
    )
    expect(cc.agents).toHaveLength(2)
    expect(cc.agents[0]).toMatchObject({ id: '0:Mateo', name: 'Mateo', role: 'detection rules', colorIndex: 0, status: 'completed' })
    expect(cc.agents[1]).toMatchObject({ id: '1:Ravi', name: 'Ravi', role: 'code review', colorIndex: 1, status: 'completed' })
  })

  it('falls back to the raw role slug, then a generic placeholder, never an invented title', () => {
    const cc = buildCcEngagementFromReal(
      engagement({ team: ['Sam (unknown-slug)', 'Just A Name'] }),
      'proj-x',
      ROLE_LABELS,
    )
    expect(cc.agents[0]!.role).toBe('unknown-slug') // no roleLabels entry -> falls back to the slug itself
    expect(cc.agents[1]!.role).toBe('Team member') // no parens at all -> no slug either -> generic placeholder
  })

  it('produces no agents for an empty team', () => {
    const cc = buildCcEngagementFromReal(engagement({ team: [] }), 'proj-x', ROLE_LABELS)
    expect(cc.agents).toEqual([])
  })
})

describe('buildCcEngagementFromReal - event-type mapping table', () => {
  // 'opened'/'closed'/'artifact' events land in timelineModel's Milestones lane - never
  // attributed to a named person. CcEvent has no "no one, the engagement itself" concept (every
  // consumer looks agentId up against the real roster, and the desktop SVG timeline already
  // silently drops unrostered events) - fromReal.ts filters these out entirely up front (see
  // isAttributedEvent) so every surface agrees, rather than Pulse/the mobile list showing a
  // broken row with the literal internal string "__milestones__" as its "agent" (a real bug,
  // found and fixed against this project's own dashboard-demo engagement, which has real
  // artifact-added events - not a hypothetical case).
  it('drops opened/closed milestone events entirely - no attributed agent exists for them', () => {
    const cc = buildCcEngagementFromReal(engagement({ opened: '2026-08-01', closed: '2026-08-05' }), 'proj-x', ROLE_LABELS)
    expect(cc.events.find((e) => e.title === 'Engagement opened')).toBeUndefined()
    expect(cc.events.find((e) => e.title === 'Engagement closed')).toBeUndefined()
  })

  it('drops artifact milestone events entirely, but the close date still counts toward durationSeconds', () => {
    const cc = buildCcEngagementFromReal(
      engagement({
        opened: '2026-08-01',
        closed: '2026-08-05',
        artifacts: [{ path: 'spec.md', absPath: '/tmp/spec.md', title: 'Spec', status: 'final', added: '2026-08-02' }],
      }),
      'proj-x',
      ROLE_LABELS,
    )
    expect(cc.events.find((e) => e.title === 'Spec')).toBeUndefined()
    // No attributed events at all here - durationSeconds still reflects the real opened->closed
    // span (4 days) from the filtered-out milestone events, not 0.
    expect(cc.durationSeconds).toBe(4 * 86400)
  })

  it('maps a plain untagged note -> tool_call', () => {
    const cc = buildCcEngagementFromReal(
      engagement({ team: ['Mateo (rules-developer)'], log: ['2026-08-03: Mateo drafted v1'] }),
      'proj-x',
      ROLE_LABELS,
    )
    expect(cc.events.find((e) => e.title === 'Mateo drafted v1')?.type).toBe('tool_call')
  })

  it('maps a resolved review-loop handoff -> loop, with targetAgentId + loopId set', () => {
    const cc = buildCcEngagementFromReal(
      engagement({
        team: ['Mateo (rules-developer)', 'Ravi (code-reviewer)'],
        log: ['2026-08-03 [review-loop]: Ravi -> Mateo: resubmit'],
      }),
      'proj-x',
      ROLE_LABELS,
    )
    const ev = cc.events.find((e) => e.type === 'loop')!
    expect(ev).toBeDefined()
    expect(ev.agentId).toBe('1:Ravi')
    expect(ev.targetAgentId).toBe('0:Mateo')
    expect(ev.loopId).toBe(cc.loops[0]!.id)
    expect(cc.loops).toHaveLength(1)
  })

  it('maps a resolved handoff with a non-review-loop tag -> handoff, no CcLoop produced', () => {
    const cc = buildCcEngagementFromReal(
      engagement({
        team: ['Mateo (rules-developer)', 'Ravi (code-reviewer)'],
        log: ['2026-08-03 [escalation]: Ravi -> Mateo: please take a look'],
      }),
      'proj-x',
      ROLE_LABELS,
    )
    const handoff = cc.events.find((e) => e.type === 'handoff')!
    expect(handoff).toBeDefined()
    expect(handoff.targetAgentId).toBe('0:Mateo')
    expect(handoff.loopId).toBeUndefined()
    expect(cc.loops).toEqual([])
  })

  it('maps an UNRESOLVED "X -> Y" shaped tagged line -> handoff, not loop, even when tagged review-loop', () => {
    const cc = buildCcEngagementFromReal(
      engagement({
        team: ['Mateo (rules-developer)'],
        log: ['2026-08-03 [review-loop]: Someone External -> Mateo: feedback'],
      }),
      'proj-x',
      ROLE_LABELS,
    )
    const ev = cc.events.find((e) => e.type === 'handoff')
    expect(ev).toBeDefined()
    expect(cc.events.some((e) => e.type === 'loop')).toBe(false)
    expect(cc.loops).toEqual([])
  })

  it('a plain tagged note (no "X -> Y" shape) always lands in the Milestones lane in timelineModel, so it never appears as a CcEvent either - the "decision" mapping in mapEventType is unreachable via this adapter today for the same reason opened/closed/artifact are (see isAttributedEvent) - documented, not a bug', () => {
    const cc = buildCcEngagementFromReal(
      engagement({ log: ['2026-08-03 [milestone]: approved, no changes needed'] }),
      'proj-x',
      ROLE_LABELS,
    )
    expect(cc.events.find((e) => e.title === 'approved, no changes needed')).toBeUndefined()
    expect(cc.events.some((e) => e.type === 'decision')).toBe(false)
  })
})

describe('buildCcEngagementFromReal - loop derivation', () => {
  it('resolves to the next plain note in the target lane within the window, using its text as the resolution', () => {
    const cc = buildCcEngagementFromReal(
      engagement({
        team: ['Mateo (rules-developer)', 'Ravi (code-reviewer)'],
        log: [
          '2026-08-03 [review-loop]: Ravi -> Mateo: resubmit',
          '2026-08-04: Mateo fixed the threshold per review feedback',
        ],
      }),
      'proj-x',
      ROLE_LABELS,
    )
    expect(cc.loops).toHaveLength(1)
    expect(cc.loops[0]!.resolution).toBe('Mateo fixed the threshold per review feedback')
    expect(cc.loops[0]!.completedAt).toBeGreaterThan(cc.loops[0]!.startedAt)
  })

  it('falls back to "Not recorded" when no qualifying note follows, never inventing one', () => {
    const cc = buildCcEngagementFromReal(
      engagement({
        team: ['Mateo (rules-developer)', 'Ravi (code-reviewer)'],
        log: ['2026-08-03 [review-loop]: Ravi -> Mateo: resubmit'],
      }),
      'proj-x',
      ROLE_LABELS,
    )
    expect(cc.loops[0]!.resolution).toBe('Not recorded')
    expect(cc.loops[0]!.completedAt).toBe(cc.loops[0]!.startedAt)
  })

  it('falls back to "Not recorded" when the only later note is in a different lane', () => {
    const cc = buildCcEngagementFromReal(
      engagement({
        team: ['Mateo (rules-developer)', 'Ravi (code-reviewer)'],
        log: [
          '2026-08-03 [review-loop]: Ravi -> Mateo: resubmit',
          '2026-08-04: Ravi started something unrelated', // lands in Ravi's own lane, not the target's (Mateo's)
        ],
      }),
      'proj-x',
      ROLE_LABELS,
    )
    expect(cc.loops[0]!.resolution).toBe('Not recorded')
  })

  it('falls back to "Not recorded" when the only later note is outside the resolution window', () => {
    const cc = buildCcEngagementFromReal(
      engagement({
        team: ['Mateo (rules-developer)', 'Ravi (code-reviewer)'],
        log: [
          '2026-08-03 [review-loop]: Ravi -> Mateo: resubmit',
          '2026-08-20: Mateo finally got back to this', // 17 days later, outside the window
        ],
      }),
      'proj-x',
      ROLE_LABELS,
    )
    expect(cc.loops[0]!.resolution).toBe('Not recorded')
  })

  it('has real-zero cost/tokens, never a fabricated non-zero figure', () => {
    const cc = buildCcEngagementFromReal(
      engagement({
        team: ['Mateo (rules-developer)', 'Ravi (code-reviewer)'],
        log: ['2026-08-03 [review-loop]: Ravi -> Mateo: resubmit'],
      }),
      'proj-x',
      ROLE_LABELS,
    )
    expect(cc.loops[0]!.cost).toBe(0)
    expect(cc.loops[0]!.tokens).toBe(0)
  })

  it('uses the arc reason for both the iteration label/detail and the loop trigger', () => {
    const cc = buildCcEngagementFromReal(
      engagement({
        team: ['Mateo (rules-developer)', 'Ravi (code-reviewer)'],
        log: ['2026-08-03 [review-loop]: Ravi -> Mateo: threshold too aggressive'],
      }),
      'proj-x',
      ROLE_LABELS,
    )
    const loop = cc.loops[0]!
    expect(loop.trigger).toBe('threshold too aggressive')
    expect(loop.iterations).toHaveLength(1)
    expect(loop.iterations[0]!.label).toBe('threshold too aggressive')
    expect(loop.iterations[0]!.detail).toBe('threshold too aggressive')
  })

  it('lists both participants (unique) in agentIds, including for a self-loop', () => {
    const cc = buildCcEngagementFromReal(
      engagement({
        team: ['Mateo (rules-developer)'],
        log: ['2026-08-03 [review-loop]: Mateo -> Mateo: re-flagged own note'],
      }),
      'proj-x',
      ROLE_LABELS,
    )
    expect(cc.loops[0]!.agentIds).toEqual(['0:Mateo'])
  })
})

describe('buildCcEngagementFromReal - time-unit conversion', () => {
  it('anchors t=0 at the opened date (even though the opened event itself is a filtered-out milestone); same-day events share a timestamp', () => {
    const cc = buildCcEngagementFromReal(
      engagement({
        opened: '2026-08-01',
        team: ['Mateo (rules-developer)'],
        log: ['2026-08-01: Mateo logged something the same day as opened', '2026-08-02: Mateo logged something one day later'],
      }),
      'proj-x',
      ROLE_LABELS,
    )
    const sameDay = cc.events.find((e) => e.title === 'Mateo logged something the same day as opened')!
    const nextDay = cc.events.find((e) => e.title === 'Mateo logged something one day later')!
    expect(sameDay.startedAt).toBe(0)
    expect(nextDay.startedAt).toBe(86400) // exactly one day, in seconds
    expect(cc.durationSeconds).toBe(86400)
  })

  it('falls back to the earliest valid-dated event as the anchor when opened is null', () => {
    // Log lines need to start with the actor's own first name for timelineModel's
    // guessPlainNoteLane heuristic to attribute them to a real lane - an unattributed note
    // would land in the (filtered-out) Milestones lane regardless of this test's actual
    // subject (anchor fallback), same reasoning as the opened/closed/artifact cases above.
    const cc = buildCcEngagementFromReal(
      engagement({
        opened: null,
        team: ['Mateo (rules-developer)'],
        log: ['2026-08-05: Mateo noted the first finding', '2026-08-07: Mateo followed up two days later'],
      }),
      'proj-x',
      ROLE_LABELS,
    )
    const first = cc.events.find((e) => e.title === 'Mateo noted the first finding')!
    const later = cc.events.find((e) => e.title === 'Mateo followed up two days later')!
    expect(first.startedAt).toBe(0)
    expect(later.startedAt).toBe(2 * 86400)
  })

  it('offsets every event to 0 (never crashes) when nothing anywhere has a valid date', () => {
    const cc = buildCcEngagementFromReal(engagement({ opened: null, log: [] }), 'proj-x', ROLE_LABELS)
    expect(cc.events).toEqual([])
    expect(cc.durationSeconds).toBe(0)
  })

  it('startClock is a fixed, honest midnight anchor, never a fabricated real time', () => {
    const cc = buildCcEngagementFromReal(engagement(), 'proj-x', ROLE_LABELS)
    expect(cc.startClock).toBe('00:00:00')
  })
})

describe('buildCcEngagementFromReal - realCostRollup', () => {
  it('carries a real costRollup through unchanged (minus the cache-token fields, per the type)', () => {
    const cc = buildCcEngagementFromReal(
      engagement({
        costRollup: {
          sessionCount: 3,
          tokensIn: 10000,
          tokensOut: 2000,
          cacheRead: 500,
          cacheWrite: 100,
          costUsd: 1.23,
          costPartial: false,
        },
      }),
      'proj-x',
      ROLE_LABELS,
    )
    expect(cc.realCostRollup).toEqual({
      costUsd: 1.23,
      tokensIn: 10000,
      tokensOut: 2000,
      sessionCount: 3,
      costPartial: false,
    })
  })

  it('omits realCostRollup entirely when costRollup is null - never a fabricated zero', () => {
    const cc = buildCcEngagementFromReal(engagement({ costRollup: null }), 'proj-x', ROLE_LABELS)
    expect(cc.realCostRollup).toBeUndefined()
    expect('realCostRollup' in cc).toBe(false)
  })
})

describe('buildCcEngagementFromReal - no fabricated per-event fields', () => {
  it('never sets cost/inputTokens/outputTokens/why/conversation on a real event', () => {
    const cc = buildCcEngagementFromReal(
      engagement({
        team: ['Mateo (rules-developer)', 'Ravi (code-reviewer)'],
        artifacts: [{ path: 'spec.md', absPath: '/tmp/spec.md', title: 'Spec', status: 'final', added: '2026-08-02' }],
        log: ['2026-08-03 [review-loop]: Ravi -> Mateo: resubmit', '2026-08-04: a plain note'],
      }),
      'proj-x',
      ROLE_LABELS,
    )
    for (const e of cc.events) {
      expect(e.cost).toBeUndefined()
      expect(e.inputTokens).toBeUndefined()
      expect(e.outputTokens).toBeUndefined()
      expect(e.why).toBeUndefined()
      expect(e.conversation).toBeUndefined()
      expect(e.status).toBe('completed')
    }
  })
})
