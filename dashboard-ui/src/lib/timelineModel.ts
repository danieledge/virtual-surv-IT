// Pure, framework-free timeline/swimlane model. No React, no DOM - independently unit-tested
// (see timelineModel.test.ts). Turns one Engagement's `team`/`artifacts`/`log`/`opened`/
// `closed` fields into lanes + ordered events + resolved "loop" arcs between two named people.
//
// Design note (why ordinal X, not linear time): dates are day-granular and sparse - a real
// engagement can have three events on one day and then a 12-day silent gap. A linear time
// scale would crush same-day back-and-forth into overlapping/illegible nodes (exactly the
// loops we most want visible) or waste most of the width on empty gaps. The layout layer
// (TeamSwimlaneTimeline) positions events ordinally with a capped log-scaled nudge for real
// date gaps; this module only produces the ordered event list + `order` index.

import type { Engagement } from './types'
import { fileUrl } from './links'

export interface Actor {
  key: string // stable, NOT bare name - "0:Mateo", "1:Mateo" if the roster has two Mateos
  name: string
  roleSlug: string | null
  roleLabel: string | null // filled in by buildTimelineModel from the roleLabels map
  raw: string // original "Name (role)" string, fallback display
  initials: string
  colorIndex: number // stable index into the actor color palette (team-array order)
}

export const MILESTONE_LANE_KEY = '__milestones__'

export type TimelineEventKind = 'opened' | 'closed' | 'artifact' | 'note' | 'tagged'

export interface TimelineEvent {
  id: string
  kind: TimelineEventKind
  date: string
  dateValid: boolean
  laneKey: string
  order: number
  icon: string
  title: string
  detail: string
  tag: string | null
  loop: boolean // true => amber ring / "rework" styling, whether or not it resolved to an arc
  href: string | null // file:// link to the underlying artifact - only 'artifact' events have one
}

export interface TimelineArc {
  id: string
  order: number // ordinal position of the originating event, shared with its anchor node
  fromLaneKey: string
  toLaneKey: string
  selfLoop: boolean
  tag: string
  reason: string
}

export interface TimelineLane {
  key: string
  label: string
  sublabel: string | null // role label, actor lanes only
  actor: Actor | null
  isMilestoneLane: boolean
}

export interface TimelineModel {
  lanes: TimelineLane[] // [Milestones, ...team-array order]
  events: TimelineEvent[] // sorted by `order`
  arcs: TimelineArc[] // resolved handoffs only (both endpoints matched a known actor)
  unresolvedTagCount: number // tagged "X -> Y" lines where a name didn't resolve to an actor
  unparsableDateCount: number
  maxOrder: number
}

const TEAM_MEMBER_RE = /^(.*?)\s*\(([^)]+)\)\s*$/
// A second team-string convention this project's own eval harness (scripts/eval_engage.py)
// writes: "🤖 Name, Role (Team)" - e.g. "🤖 Ravi, Code Reviewer (Virtual Surveillance IT)" -
// rather than this file's own "Name (role-slug)" convention. The comma before the role is the
// distinguishing signal (real single first-names in this roster never contain one) - matched
// FIRST in parseTeamMember, since TEAM_MEMBER_RE would otherwise also match this shape, just
// with the wrong split (name would end up as "🤖 Ravi, Code Reviewer", role as "Virtual
// Surveillance IT" - neither useful). 2026-08-09 live finding: real review-loop handoffs using
// slug tokens like "code-reviewer" silently failed to resolve to any actor because of this, so
// genuine rework moments in a real engagement never rendered - traced and fixed, not
// hypothetical. Mirrored in scripts/dashboard.py's _TEAM_MEMBER_COMMA_RE - keep both in sync.
const TEAM_MEMBER_COMMA_RE = /^(.*?),\s*(.+?)\s*\([^)]*\)\s*$/
const TAGGED_LOG_RE = /^(\d{4}-\d{2}-\d{2}) \[([^\]]+)\]: (.*)$/
const PLAIN_LOG_RE = /^(\d{4}-\d{2}-\d{2}): (.*)$/
const HANDOFF_RE = /^(.+?)\s*->\s*(.+?):\s*(.*)$/
const TAG_ICONS: Record<string, string> = { 'review-loop': '\u{1F501}' } // 🔁

export function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase()
  return (parts[0]![0] + parts[parts.length - 1]![0]).toUpperCase()
}

/** Free-text role ("Code Reviewer") -> the lowercase-hyphenated slug convention role labels/
 * log-line handoff tokens actually use ("code-reviewer") - collapses any run of
 * non-alphanumerics to one hyphen, trims the ends. Mirrors scripts/dashboard.py's _slugify. */
function slugify(text: string): string {
  return text
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

/** One team-array entry -> an Actor - either "Name (role-slug)" or "🤖 Name, Role (Team)" (see
 * TEAM_MEMBER_COMMA_RE's own comment for why the second shape exists and is tried first).
 * Malformed entries (neither shape) still get a real lane - never dropped, per the design's
 * edge-case #7. */
export function parseTeamMember(raw: string, index: number): Actor {
  const trimmed = raw.trim().replace(/^\u{1F916}\s*/u, '') // strip a leading 🤖, if present

  const commaMatch = TEAM_MEMBER_COMMA_RE.exec(trimmed)
  if (commaMatch) {
    const name = commaMatch[1]!.trim() || `Member ${index + 1}`
    const roleSlug = slugify(commaMatch[2]!) || null
    return {
      key: `${index}:${name}`,
      name,
      roleSlug,
      roleLabel: null,
      raw,
      initials: initialsOf(name),
      colorIndex: index,
    }
  }

  const match = TEAM_MEMBER_RE.exec(trimmed)
  const name = (match ? match[1]!.trim() : trimmed) || `Member ${index + 1}`
  const roleSlug = match ? match[2]!.trim() : null
  return {
    key: `${index}:${name}`,
    name,
    roleSlug,
    roleLabel: null,
    raw,
    initials: initialsOf(name),
    colorIndex: index,
  }
}

export interface ParsedLogLine {
  date: string
  tag: string | null
  text: string
}

/** The two log-line shapes `engagement_state.log-note`/`--tag` write. Neither shape matching
 * (a hand-edited state file, a v1-schema leftover) returns null rather than guessing. */
export function parseLogLine(line: string): ParsedLogLine | null {
  const tagged = TAGGED_LOG_RE.exec(line)
  if (tagged) return { date: tagged[1]!, tag: tagged[2]!, text: tagged[3]! }
  const plain = PLAIN_LOG_RE.exec(line)
  if (plain) return { date: plain[1]!, tag: null, text: plain[2]! }
  return null
}

function resolveActorToken(token: string, actors: Actor[]): Actor | null {
  const raw = token.trim().toLowerCase()
  const stripped = raw.replace(/\s*\([^)]*\)\s*$/, '').trim() // tolerate an already-humanized
  // token like "Ravi (code review)" showing up in hand-written log text
  for (const a of actors) {
    const name = a.name.toLowerCase()
    if (name === raw || name === stripped) return a
  }
  for (const a of actors) {
    if (a.roleSlug && a.roleSlug.toLowerCase() === raw) return a
  }
  return null
}

export interface HandoffParse {
  fromToken: string
  toToken: string
  fromKey: string | null // resolved actor key, or null if the name didn't match anyone
  toKey: string | null
  reason: string
}

/** Parses "X -> Y: reason" out of a tagged log line's text (date/tag already stripped by
 * parseLogLine). Returns null only when the text doesn't match the SHAPE at all (a plain
 * tagged note, e.g. "approved, no changes needed") - a shape match with an unresolved name
 * still returns an object (fromKey/toKey null), so the caller can decide plain-node-vs-arc
 * placement rather than silently dropping a real tagged event. */
export function parseHandoff(text: string, actors: Actor[]): HandoffParse | null {
  const m = HANDOFF_RE.exec(text)
  if (!m) return null
  const [, fromToken, toToken, reason] = m
  return {
    fromToken: fromToken!.trim(),
    toToken: toToken!.trim(),
    fromKey: resolveActorToken(fromToken!, actors)?.key ?? null,
    toKey: resolveActorToken(toToken!, actors)?.key ?? null,
    reason: reason!.trim(),
  }
}

function isValidIsoDate(s: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return false
  const d = new Date(`${s}T00:00:00Z`)
  if (Number.isNaN(d.getTime())) return false
  // Round-trip and compare: some engines silently NORMALIZE an out-of-range calendar date
  // (e.g. "2026-02-30" rolls over to March) instead of failing to parse - a plain
  // Date.parse !isNaN check misses that. Comparing the reconstructed ISO string catches it.
  return d.toISOString().slice(0, 10) === s
}

/** First-token-name heuristic for a PLAIN (untagged) note's cosmetic lane placement only -
 * ambiguous (zero or 2+ matches, e.g. two actors sharing a first name) falls back to the
 * Milestones lane. Silent misattribution is worse than "unattributed" (edge case #6). */
function guessPlainNoteLane(text: string, actors: Actor[]): string {
  const firstWord = text.trim().split(/\s+/)[0]?.replace(/[.,:;]+$/, '')
  if (!firstWord) return MILESTONE_LANE_KEY
  const w = firstWord.toLowerCase()
  const matches = actors.filter((a) => a.name.split(/\s+/)[0]?.toLowerCase() === w)
  return matches.length === 1 ? matches[0]!.key : MILESTONE_LANE_KEY
}

interface RawEvent {
  rawIndex: number
  date: string
  kind: TimelineEventKind
  icon: string
  title: string
  detail: string
  tag: string | null
  loop: boolean
  laneKey: string
  href: string | null
}

interface PendingArc {
  originRawIndex: number
  fromLaneKey: string
  toLaneKey: string
  selfLoop: boolean
  tag: string
  reason: string
}

export function buildTimelineModel(
  engagement: Engagement,
  roleLabels: Record<string, string>
): TimelineModel {
  const actors: Actor[] = (engagement.team || []).map((raw, i) => {
    const a = parseTeamMember(raw, i)
    return { ...a, roleLabel: a.roleSlug ? (roleLabels[a.roleSlug] ?? null) : null }
  })

  const lanes: TimelineLane[] = [
    {
      key: MILESTONE_LANE_KEY,
      label: 'Milestones',
      sublabel: null,
      actor: null,
      isMilestoneLane: true,
    },
    ...actors.map((a) => ({
      key: a.key,
      label: a.name,
      sublabel: a.roleLabel,
      actor: a,
      isMilestoneLane: false,
    })),
  ]

  const raw: RawEvent[] = []
  const pendingArcs: PendingArc[] = []
  let unresolvedTagCount = 0
  let unparsableDateCount = 0
  const push = (e: Omit<RawEvent, 'rawIndex' | 'href'> & { href?: string | null }): number => {
    const idx = raw.length
    raw.push({ rawIndex: idx, href: null, ...e }) // href defaults to null; only the
    // artifact push site below overrides it - every other event kind has no underlying file
    return idx
  }

  if (engagement.opened) {
    push({
      date: engagement.opened,
      kind: 'opened',
      icon: '\u{1F6A9}', // 🚩
      title: 'Engagement opened',
      detail: 'Engagement opened',
      tag: null,
      loop: false,
      laneKey: MILESTONE_LANE_KEY,
    })
  }

  for (const art of engagement.artifacts || []) {
    if (!art.added) continue
    const title = art.title || art.path || 'artifact'
    push({
      date: art.added,
      kind: 'artifact',
      icon: '\u{1F4C4}', // 📄
      title,
      detail: `${title} (${art.status})`,
      tag: null,
      loop: false,
      laneKey: MILESTONE_LANE_KEY,
      href: fileUrl(art.absPath),
    })
  }

  for (const line of engagement.log || []) {
    const parsed = parseLogLine(line)
    if (!parsed) continue
    if (!isValidIsoDate(parsed.date)) unparsableDateCount++

    if (parsed.tag) {
      const handoff = parseHandoff(parsed.text, actors)
      if (handoff) {
        if (handoff.fromKey && handoff.toKey) {
          const idx = push({
            date: parsed.date,
            kind: 'tagged',
            icon: TAG_ICONS[parsed.tag] ?? '\u{1F516}', // 🔖 fallback
            title: `${handoff.fromToken} → ${handoff.toToken}`,
            detail: handoff.reason,
            tag: parsed.tag,
            loop: true,
            laneKey: handoff.fromKey,
          })
          pendingArcs.push({
            originRawIndex: idx,
            fromLaneKey: handoff.fromKey,
            toLaneKey: handoff.toKey,
            selfLoop: handoff.fromKey === handoff.toKey,
            tag: parsed.tag,
            reason: handoff.reason,
          })
          continue
        }
        // shape matched but one/neither side resolved - still a real flagged event, no arc
        unresolvedTagCount++
        push({
          date: parsed.date,
          kind: 'tagged',
          icon: TAG_ICONS[parsed.tag] ?? '\u{1F516}',
          title: parsed.text,
          detail: parsed.text,
          tag: parsed.tag,
          loop: true,
          laneKey: handoff.fromKey || handoff.toKey || MILESTONE_LANE_KEY,
        })
        continue
      }
      // tagged, but not an "X -> Y:" shape - a plain tagged note (e.g. a milestone tag)
      push({
        date: parsed.date,
        kind: 'tagged',
        icon: TAG_ICONS[parsed.tag] ?? '\u{1F516}',
        title: parsed.text,
        detail: parsed.text,
        tag: parsed.tag,
        loop: false,
        laneKey: MILESTONE_LANE_KEY,
      })
      continue
    }

    push({
      date: parsed.date,
      kind: 'note',
      icon: '\u{1F4DD}', // 📝
      title: parsed.text,
      detail: parsed.text,
      tag: null,
      loop: false,
      laneKey: guessPlainNoteLane(parsed.text, actors),
    })
  }

  if (engagement.closed) {
    push({
      date: engagement.closed,
      kind: 'closed',
      icon: '✅', // ✅
      title: 'Engagement closed',
      detail: 'Engagement closed',
      tag: null,
      loop: false,
      laneKey: MILESTONE_LANE_KEY,
    })
  }

  // Stable sort by date; original push order (opened -> artifacts -> log -> closed, array
  // order within each) is the tiebreak - matches scripts/dashboard.py's own event sequencing.
  const ordered = raw
    .map((e, pushOrder) => ({ e, pushOrder }))
    .sort((a, b) => (a.e.date < b.e.date ? -1 : a.e.date > b.e.date ? 1 : a.pushOrder - b.pushOrder))

  const rawIndexToOrder = new Map<number, number>()
  const events: TimelineEvent[] = ordered.map(({ e }, order) => {
    rawIndexToOrder.set(e.rawIndex, order)
    return {
      id: `ev-${order}`,
      kind: e.kind,
      date: e.date,
      dateValid: isValidIsoDate(e.date),
      laneKey: e.laneKey,
      order,
      icon: e.icon,
      title: e.title,
      detail: e.detail,
      tag: e.tag,
      loop: e.loop,
      href: e.href,
    }
  })

  // Arc x-position is recovered via the shared rawIndex, NOT push order - sorting can reorder
  // tagged events relative to each other when dates differ, so a naive index-zip would
  // silently mispair an arc with the wrong node once that happens.
  const arcs: TimelineArc[] = pendingArcs.map((p, i) => ({
    id: `arc-${i}`,
    order: rawIndexToOrder.get(p.originRawIndex) ?? 0,
    fromLaneKey: p.fromLaneKey,
    toLaneKey: p.toLaneKey,
    selfLoop: p.selfLoop,
    tag: p.tag,
    reason: p.reason,
  }))

  return {
    lanes,
    events,
    arcs,
    unresolvedTagCount,
    unparsableDateCount,
    maxOrder: events.length ? events.length - 1 : 0,
  }
}
