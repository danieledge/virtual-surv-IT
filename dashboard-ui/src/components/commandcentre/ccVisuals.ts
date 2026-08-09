// Shared visual mappings for the Command Centre - event-type semantics and the agent lane
// color helper, kept in one place so the header, pulse strip, hero timeline, and cost bars all
// agree on what a given agent or event type looks like. Pure data/functions only - the
// EventTypeIcon component lives in ccIcons.tsx (a separate file so this one stays plain .ts and
// React Fast Refresh doesn't warn about a file mixing components with other exports).

import type { CcEventType } from '../../lib/commandCentre/types'

export type EventTone = 'neutral' | 'accent' | 'loop' | 'error' | 'success'

interface EventTypeMeta {
  label: string
  tone: EventTone
}

export const EVENT_TYPE_META: Record<CcEventType, EventTypeMeta> = {
  started: { label: 'Started', tone: 'neutral' },
  spawned: { label: 'Spawned', tone: 'accent' },
  discovery: { label: 'Discovery', tone: 'accent' },
  handoff: { label: 'Handoff', tone: 'accent' },
  escalation: { label: 'Escalation', tone: 'error' },
  tool_call: { label: 'Tool Call', tone: 'neutral' },
  error: { label: 'Error', tone: 'error' },
  retry: { label: 'Retry', tone: 'loop' },
  loop: { label: 'Loop', tone: 'loop' },
  decision: { label: 'Decision', tone: 'accent' },
  human: { label: 'Human', tone: 'success' },
  resolution: { label: 'Resolution', tone: 'success' },
}

/** Event types shown on the Engagement Pulse strip - a fast-scan overview, not a full log, so
 * routine tool_call/spawned/started noise is deliberately left off. */
export const PULSE_EVENT_TYPES: ReadonlySet<CcEventType> = new Set([
  'discovery',
  'handoff',
  'escalation',
  'loop',
  'decision',
  'human',
  'resolution',
  'error',
  'retry',
])

// Round 3 (dashboard reskin): these used to point at commandcentre.css's own isolated --cc-*
// token world. They now point at the SAME shared tokens the rest of the app uses
// (src/index.css) - 'loop' deliberately reuses --warn rather than a dedicated color: nothing
// else in the Command Centre uses --warn, so amber unambiguously means "rework" here, exactly
// the meaning index.css's own actor-palette comment already reserves that hue for app-wide.
export function toneVar(tone: EventTone): string {
  switch (tone) {
    case 'accent':
      return 'var(--accent)'
    case 'loop':
      return 'var(--warn)'
    case 'error':
      return 'var(--bad)'
    case 'success':
      return 'var(--ok)'
    default:
      return 'var(--muted)'
  }
}

/** Cycles mod 6 against the shared 6-color actor palette (--actor-1..--actor-6 in
 * src/index.css) - the SAME palette the other swimlane timeline elsewhere in the app already
 * uses for the same conceptual purpose (agent/actor identity color), not a separate --agent-*
 * family. Matches CcAgent.colorIndex's own doc comment on staying stable across the whole view. */
export function agentColorVar(colorIndex: number): string {
  return `var(--actor-${(colorIndex % 6) + 1})`
}

/** Compact "98.4k" / "1.82M" style formatter for header trend labels and sidebar totals - never
 * used anywhere a cost needs exact precision (costs stay $X.XX everywhere they're shown). */
export function formatCompact(n: number): string {
  const abs = Math.abs(n)
  if (abs >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (abs >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(Math.round(n))
}
