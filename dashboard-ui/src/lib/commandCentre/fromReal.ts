// Real-data adapter for the Engagement Command Centre - turns one real `Engagement` (this
// project's actual data model, lib/types.ts) into a `CcEngagement` (the Command Centre's richer
// shell, lib/commandCentre/types.ts). Pure, framework-free, Vitest-covered (fromReal.test.ts),
// same discipline as lib/timelineModel.ts. Reuses `buildTimelineModel` for all the real parsing
// (actor attribution, resolved handoffs, review-loop arcs) rather than re-parsing `log` itself -
// see the plan this was built from (approved via AskUserQuestion) for the full rationale.
//
// What's real vs. missing (grounds every mapping decision below): real, usable - team roster,
// per-line agent attribution, resolved handoffs, review-loop-tagged rework moments, artifacts,
// whole-engagement cost/token totals (costRollup). Missing entirely, left unset rather than
// guessed - per-event timestamps finer than a day, per-event cost/tokens, confidence scores,
// real conversation text, live agent status.
//
// No Date.now()/bare `new Date()` anywhere below - only deterministic parsing of the fixed ISO
// date strings already present in the data, same safe `${s}T00:00:00Z` pattern
// timelineModel.ts's own (unexported) isValidIsoDate already uses.

import type { Engagement, EngagementStatus } from '../types'
import type { TimelineArc, TimelineEvent, TimelineModel } from '../timelineModel'
import { buildTimelineModel, MILESTONE_LANE_KEY } from '../timelineModel'
import type { CcAgent, CcEngagement, CcEvent, CcEventType, CcLoop } from './types'

/** A plain-note resolution has to land within this many days of the arc's own date to count as
 * "the" resolution - the plan's own wording ("within a few days") doesn't pin an exact number;
 * a week is a judgment call (generous enough to catch a same-week follow-up note, tight enough
 * that an unrelated note months later never gets misattributed as this loop's resolution). Not
 * a detection threshold (no regulatory obligation rides on it), but documented per this
 * project's own "no unexplained magic numbers" convention anyway. */
const RESOLUTION_WINDOW_DAYS = 7

/** Real Engagement.status -> the Command Centre's coarser 3-way status. `closing` (still open,
 * wrapping up) maps to `investigating` rather than `resolved` - it isn't done yet. `invalid`
 * (a corrupt/unparsable engagement-state.json, see scripts/engagement_state.py) maps to
 * `blocked` - not because the WORK is blocked, but because something about the record itself
 * needs attention, and `blocked` is the closest of the three honest options for "this needs a
 * human look before treating it as either progressing or done". Neither mapping is specified by
 * the plan's own type-changes section; both are judgment calls. */
const STATUS_MAP: Record<EngagementStatus | 'invalid', CcEngagement['status']> = {
  in_progress: 'investigating',
  closing: 'investigating',
  blocked: 'blocked',
  closed: 'resolved',
  invalid: 'blocked',
}

function toUtcMs(isoDate: string): number {
  return new Date(`${isoDate}T00:00:00Z`).getTime()
}

/** Event-type mapping table (documented here AND in the plan this was built from):
 *   opened                                          -> started
 *   closed                                          -> resolution
 *   artifact                                        -> discovery
 *   note                                             -> tool_call
 *   tagged, "X -> Y" shape, BOTH sides resolved,
 *     tag === 'review-loop'                          -> loop
 *   tagged, "X -> Y" shape, BOTH sides resolved,
 *     any other tag                                  -> handoff
 *   tagged, "X -> Y" shape, but NOT both sides
 *     resolved (unresolvedTagCount case)              -> handoff
 *   tagged, not an "X -> Y" shape at all (plain
 *     tagged note)                                    -> decision
 *
 * The "shape matched but unresolved" row isn't spelled out as its own bullet in the plan (which
 * only names "resolved-handoff"/"handoff"/"not-a-handoff-shape") - it's bucketed into `handoff`
 * here as the closest honest fit: it's still structurally a handoff attempt (someone flagged
 * work for someone else), just one this log's team roster couldn't fully resolve, so it can
 * never become a `loop` (a CcLoop needs both a real origin AND a real target actor - see
 * `buildLoops` below, which only ever draws from resolved arcs). A judgment call, flagged here.
 *
 * The `decision` row (tagged, not an "X -> Y" shape) is real but currently UNREACHABLE via
 * `buildCcEngagementFromReal`: timelineModel.ts always places that shape in the Milestones lane
 * (never attributed to a person, regardless of roster), and `isAttributedEvent` below filters
 * every Milestones-lane event out before this function even runs on it - same reasoning as
 * opened/closed/artifact. Kept in the switch for shape-completeness/documentation, not dead
 * code by accident.
 */
function mapEventType(event: TimelineEvent, hasResolvedArc: boolean): CcEventType {
  switch (event.kind) {
    case 'opened':
      return 'started'
    case 'closed':
      return 'resolution'
    case 'artifact':
      return 'discovery'
    case 'note':
      return 'tool_call'
    case 'tagged':
      if (!event.loop) return 'decision' // not an "X -> Y" shape at all
      if (hasResolvedArc && event.tag === 'review-loop') return 'loop'
      return 'handoff'
  }
}

function buildAgents(model: TimelineModel): CcAgent[] {
  return model.lanes
    .filter((lane) => !lane.isMilestoneLane && lane.actor)
    .map((lane) => {
      const actor = lane.actor!
      return {
        id: actor.key,
        name: actor.name,
        // roleLabel (humanized) first, falling back to the raw role slug, then a generic but
        // honest placeholder - never an invented specific title.
        role: actor.roleLabel ?? actor.roleSlug ?? 'Team member',
        status: 'completed', // historical replay - no live state to show, same as the fixture's
        // own agents all being 'completed'.
        colorIndex: actor.colorIndex,
      }
    })
}

/** Anchors t=0 at `engagement.opened` when it parsed to a valid date (the model already ran
 * that validation for us - see the `opened`-kind event's own `dateValid`); falls back to the
 * earliest valid-dated event when `opened` is missing/invalid, so a malformed or absent open
 * date never crashes the offset math, it just floats the anchor to the earliest thing we DO
 * know a real date for. Returns null only when nothing in the engagement has a valid date at
 * all - every event's offset is then 0 (honest: no real timeline exists to place them on). */
function resolveAnchorMs(model: TimelineModel): number | null {
  const openedEvent = model.events.find((e) => e.kind === 'opened')
  if (openedEvent && openedEvent.dateValid) return toUtcMs(openedEvent.date)
  const validDates = model.events.filter((e) => e.dateValid).map((e) => toUtcMs(e.date))
  return validDates.length > 0 ? Math.min(...validDates) : null
}

function offsetSecondsFor(event: TimelineEvent, anchorMs: number | null): number {
  if (anchorMs === null || !event.dateValid) return 0
  return (toUtcMs(event.date) - anchorMs) / 1000
}

/** The next plain `note` event in the arc's target lane, strictly after the arc's own event in
 * chronological order (`order`, which already tie-breaks same-day lines by log position - see
 * timelineModel.ts), within RESOLUTION_WINDOW_DAYS. `model.events` is already sorted ascending
 * by `order`, so the first match `.find()` hits is the nearest one; since dates only increase
 * (or tie) as `order` increases, if the nearest candidate is already outside the window every
 * later one is too, so a single predicate-embedded `.find()` is sufficient - no need to keep
 * scanning past a window miss. Returns null (never a guess) when the origin event's own date
 * didn't parse (no basis to bound a window at all) or nothing qualifies. */
function findResolutionNote(model: TimelineModel, arc: TimelineArc): TimelineEvent | null {
  const origin = model.events.find((e) => e.order === arc.order)
  if (!origin || !origin.dateValid) return null
  const originMs = toUtcMs(origin.date)
  return (
    model.events.find((e) => {
      if (e.order <= arc.order || e.kind !== 'note' || e.laneKey !== arc.toLaneKey || !e.dateValid) return false
      const diffDays = (toUtcMs(e.date) - originMs) / 86_400_000
      return diffDays >= 0 && diffDays <= RESOLUTION_WINDOW_DAYS
    }) ?? null
  )
}

/** `opened`/`closed`/`artifact` events land in timelineModel's Milestones lane - never
 * attributed to a named person, unlike everything else this adapter maps. `CcAgent`/`CcEvent`
 * have no equivalent "no one, the engagement itself" concept (CcEvent.agentId is required and
 * every consumer - AgentTimeline's SVG, the mobile lists, EngagementPulse - looks it up against
 * the real roster), so there's nowhere honest to put them. The desktop SVG timeline
 * (buildTimelineLayout) already silently drops any event whose agentId isn't in the roster;
 * filtering here up front makes every surface agree instead of Pulse/the mobile list showing a
 * broken row with the literal internal string "__milestones__" as its "agent" (caught live
 * against this project's own dashboard-demo engagement, which has real artifact-added events -
 * a real bug, not a hypothetical one). A "Milestones" lane for the Command Centre is a
 * reasonable future enhancement; out of scope for this pass. */
function isAttributedEvent(event: TimelineEvent): boolean {
  return event.laneKey !== MILESTONE_LANE_KEY
}

function buildEvents(model: TimelineModel, anchorMs: number | null): CcEvent[] {
  const arcByOrder = new Map(model.arcs.map((arc) => [arc.order, arc]))
  const loopArcs = model.arcs.filter((arc) => arc.tag === 'review-loop')
  const loopIdByOrder = new Map(loopArcs.map((arc) => [arc.order, `loop-${arc.id}`]))

  return model.events.filter(isAttributedEvent).map((event) => {
    const arc = arcByOrder.get(event.order)
    const type = mapEventType(event, arc !== undefined)
    const offset = offsetSecondsFor(event, anchorMs)
    const ccEvent: CcEvent = {
      id: event.id,
      startedAt: offset,
      completedAt: offset, // day-granular real data has no sub-day duration to place a real
      // width on - a point event, same treatment the fixture already gives its own
      // instantaneous events (e.g. 'discovery'/'decision' entries with startedAt === completedAt).
      type,
      agentId: event.laneKey,
      title: event.title,
      summary: event.detail,
      status: 'completed', // historical replay - no live/failed/waiting state exists for a
      // parsed log line, same reasoning as CcAgent.status above.
    }
    if (arc) ccEvent.targetAgentId = arc.toLaneKey
    if (type === 'loop') ccEvent.loopId = loopIdByOrder.get(event.order)
    return ccEvent
  })
}

function buildLoops(model: TimelineModel, events: CcEvent[]): CcLoop[] {
  const eventById = new Map(events.map((e) => [e.id, e]))
  return model.arcs
    .filter((arc) => arc.tag === 'review-loop')
    .map((arc) => {
      const originTimelineEvent = model.events.find((e) => e.order === arc.order)!
      const originEvent = eventById.get(originTimelineEvent.id)!
      const resolutionNote = findResolutionNote(model, arc)
      const resolutionEvent = resolutionNote ? eventById.get(resolutionNote.id) : undefined

      return {
        id: `loop-${arc.id}`,
        startedAt: originEvent.startedAt,
        // Real resolution time when found; otherwise the origin's own time (zero-width - we
        // genuinely don't know how long it took, so we don't invent a span). Derived from the
        // already-computed CcEvent offsets, never a fresh anchor calculation.
        completedAt: resolutionEvent ? resolutionEvent.startedAt : originEvent.startedAt,
        agentIds: Array.from(new Set([arc.fromLaneKey, arc.toLaneKey])),
        // Plan: "iterations: a single entry (label/detail = the arc's reason)" - real data has
        // no per-iteration breakdown, only the one logged reason string, used for both fields.
        iterations: [{ eventId: originEvent.id, label: arc.reason, detail: arc.reason }],
        trigger: arc.reason,
        resolution: resolutionNote ? resolutionNote.detail : 'Not recorded',
        cost: 0, // real zero - no per-event cost exists to sum, never a fabricated non-zero figure
        tokens: 0,
      }
    })
}

export function buildCcEngagementFromReal(
  engagement: Engagement,
  projectName: string,
  roleLabels: Record<string, string>,
): CcEngagement {
  const model = buildTimelineModel(engagement, roleLabels)
  const anchorMs = resolveAnchorMs(model)
  const agents = buildAgents(model)
  const events = buildEvents(model, anchorMs)
  const loops = buildLoops(model, events)
  // Duration spans the FULL model (including the milestone-lane 'opened'/'closed'/'artifact'
  // events buildEvents filters out of the rendered set above) - dropping the close-date marker
  // from the timeline nodes shouldn't also shrink the header's honest elapsed-time figure if
  // the engagement's real close date falls later than its last person-attributed log line.
  const allOffsets = model.events.map((e) => offsetSecondsFor(e, anchorMs))
  const durationSeconds = allOffsets.length > 0 ? Math.max(0, ...allOffsets) : 0

  const ccEngagement: CcEngagement = {
    id: `${projectName}/${engagement.slug}`,
    name: engagement.title ?? engagement.slug,
    type: engagement.profile ?? 'Engagement',
    status: STATUS_MAP[engagement.status],
    // No real intraday time exists (day-granular data only) - '00:00:00' is a deliberate,
    // honest anchor (midnight of the opened/anchor date), not a claim of real precision. See
    // EngagementHeader.tsx, which no longer prefixes this with "Today," now that the fixture
    // (the one case where "today" was ever literally true) is retired.
    startClock: '00:00:00',
    durationSeconds,
    // confidence intentionally omitted - no confidence score exists anywhere in real data.
    agents,
    events,
    loops,
    synthetic: false,
  }

  if (engagement.costRollup) {
    ccEngagement.realCostRollup = {
      costUsd: engagement.costRollup.costUsd,
      tokensIn: engagement.costRollup.tokensIn,
      tokensOut: engagement.costRollup.tokensOut,
      sessionCount: engagement.costRollup.sessionCount,
      costPartial: engagement.costRollup.costPartial,
    }
  }

  return ccEngagement
}
