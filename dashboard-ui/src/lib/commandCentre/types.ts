// Engagement Command Centre — data model.
//
// This is a DELIBERATELY SEPARATE type system from lib/types.ts (the real emit_json() shape).
// The Command Centre visualizes event-level telemetry (per-agent tool calls, handoff
// request/response summaries, confidence scores, live replay) that nothing in this project's
// actual data model captures today - engagement-state.json has no agent-to-agent event bus,
// and Claude Code session transcripts record token usage per message, not per named "agent"
// with a request/response summary. Building that instrumentation for real is a separate,
// larger project (see docs/adr - not written yet).
//
// `synthetic` used to be a hard `true` (this view was fixture-only, see git history for the
// retired lib/commandCentre/fixtureEngagement.ts) - it's now a real boolean, always `false` in
// practice since lib/commandCentre/fromReal.ts is the only remaining producer, but the field
// (and the UI's demo-badge conditional on it) stays: defensive, honest, costs nothing to keep,
// and is exactly the switch the original comment here anticipated.

export type AgentStatus =
  | 'idle'
  | 'thinking'
  | 'running'
  | 'waiting'
  | 'delegating'
  | 'evaluating'
  | 'error'
  | 'completed'

export interface CcAgent {
  id: string
  name: string
  role: string
  status: AgentStatus
  /** Cycles mod 6 against the same 6-color lane palette used throughout, so an agent's color
   * is stable across the header, timeline lanes, and cost breakdown. */
  colorIndex: number
}

export type CcEventType =
  | 'started'
  | 'spawned'
  | 'discovery'
  | 'handoff'
  | 'escalation'
  | 'tool_call'
  | 'error'
  | 'retry'
  | 'loop'
  | 'decision'
  | 'human'
  | 'resolution'

export type CcEventStatus = 'active' | 'completed' | 'failed' | 'waiting'

export interface CcWhy {
  trigger: string
  objective?: string
  confidenceBefore?: number
  confidenceAfter?: number
  outcome: string
}

export interface CcMessage {
  agentId: string
  text: string
  tokens: number
  cost: number
}

export interface CcConversation {
  request: CcMessage
  response: CcMessage
  /** One-line synthesis of the exchange's outcome, shown under both messages - distinct from
   * CcWhy.outcome, which explains a decision/loop's reasoning rather than summarizing a
   * request/response pair. */
  result?: string
}

export interface CcEvent {
  id: string
  /** Seconds from engagement start - deliberately relative, not a wall-clock/epoch value, so
   * the fixture never needs Date.now()/new Date() (disallowed in this codebase's scripted
   * contexts, and pointless here - a static demo has no real "now"). Rendered against
   * ENGAGEMENT.startClock (a fixed "HH:MM:SS" string) purely for display. */
  startedAt: number
  completedAt: number
  type: CcEventType
  agentId: string
  /** Present for handoff-shaped events (handoff, escalation, and loop iterations that hand
   * work to another agent). */
  targetAgentId?: string
  /** Groups an event into a CcLoop.iterations entry when set. */
  loopId?: string
  /** The error event a retry resolves, when type === 'retry'. */
  retriesEventId?: string
  title: string
  summary: string
  status: CcEventStatus
  inputTokens?: number
  outputTokens?: number
  /** USD. Omitted (not zero) for events with no direct model cost, e.g. a pure human event. */
  cost?: number
  why?: CcWhy
  /** A real two-party request/response exchange, when this event represents one (a handoff or
   * a decision that involved asking another agent something). Not present on every event -
   * only where the fixture has genuine exchange content to show, never synthesized on the fly
   * by a component from a one-line summary. */
  conversation?: CcConversation
}

export interface CcLoopIteration {
  eventId: string
  label: string
  detail: string
}

export interface CcLoop {
  id: string
  startedAt: number
  completedAt: number
  agentIds: string[]
  iterations: CcLoopIteration[]
  trigger: string
  resolution: string
  /** Sum of the cost/tokens of every event in `iterations` - computed at fixture-build time
   * from the real per-event figures below, never an independently invented headline number. */
  cost: number
  tokens: number
}

/** Engagement.costRollup (lib/types.ts), carried through unchanged - see fromReal.ts's own doc
 * comment for why this exists alongside (never instead of) the event-sum totals
 * EngagementHeader already computes: real events carry no per-event cost/tokens, so that sum is
 * honestly zero for a real engagement, while this whole-engagement total is real, computed data
 * one level up. Omitted (not present) when the source Engagement.costRollup is null. */
export interface CcRealCostRollup {
  costUsd: number
  tokensIn: number
  tokensOut: number
  sessionCount: number
  costPartial: boolean
}

export interface CcEngagement {
  id: string
  name: string
  type: string
  status: 'investigating' | 'resolved' | 'blocked'
  /** Fixed "HH:MM:SS" the relative event clock is rendered against - a display anchor, not a
   * real timestamp. */
  startClock: string
  /** Seconds - total engagement span, i.e. the last event's completedAt. */
  durationSeconds: number
  /** Omitted for real engagements - no confidence score is recorded anywhere today; showing one
   * would be fabricated, not inferred. Only ever set by fixture-style data. */
  confidence?: number
  agents: CcAgent[]
  events: CcEvent[]
  loops: CcLoop[]
  synthetic: boolean
  /** Present only when the source Engagement carried a non-null costRollup - see
   * CcRealCostRollup's own doc comment. */
  realCostRollup?: CcRealCostRollup
}
