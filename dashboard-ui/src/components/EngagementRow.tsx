import { useEffect, useMemo, useState } from 'react'
import type { Engagement } from '../lib/types'
import { STATUS_MARK, daySpan, settingsChips } from '../lib/engagement'
import { engagementAnchorId } from '../lib/links'
import { formatCost } from '../lib/format'
import { buildCcEngagementFromReal } from '../lib/commandCentre/fromReal'
import { CommandCentre } from './commandcentre/CommandCentre'
import { Badge } from './ui/Badge'

interface EngagementRowProps {
  engagement: Engagement
  roleLabels: Record<string, string>
  projectName: string
  highlighted?: boolean
}

// Collapsed by default, one <details> per engagement ("expand engagement to see details",
// 2026-08-09) - the summary line carries everything needed to recognise/pick an engagement
// without opening it; opening reveals its settings + the full Command Centre (roster swimlane,
// pulse, replay, event/loop detail) for THIS engagement specifically. There used to be a
// separate, freestanding "Engagement Command Centre" section elsewhere on the page with its own
// picker - retired the same day ("an engagement is always inside a project") in favor of this:
// the Command Centre now only ever renders here, nested under the engagement it belongs to.
//
// Controlled (not the ref-toggle ProjectCard uses) because open-state gates whether the Command
// Centre - real work: buildTimelineModel + a requestAnimationFrame replay loop - mounts at all;
// a collapsed row should cost nothing.
export function EngagementRow({ engagement: e, roleLabels, projectName, highlighted }: EngagementRowProps) {
  const mark = STATUS_MARK[e.status] ?? { icon: '?' }
  const span = daySpan(e.opened, e.closed)
  const chips = settingsChips(e.settingsSnapshot)
  const [isOpen, setIsOpen] = useState(false)

  // Cross-tab nav targets one specific engagement - if this is it, open so the scroll (App's
  // own effect, targeting this same id) lands on visible content, not something still hidden.
  useEffect(() => {
    if (highlighted) setIsOpen(true)
  }, [highlighted])

  const ccEngagement = useMemo(
    () => (isOpen ? buildCcEngagementFromReal(e, projectName, roleLabels) : null),
    [isOpen, e, projectName, roleLabels],
  )

  return (
    <details
      id={engagementAnchorId(projectName, e.slug)}
      open={isOpen}
      onToggle={(event) => setIsOpen(event.currentTarget.open)}
      className={`group scroll-mt-4 rounded-xl border border-border bg-surface-1 p-3 sm:p-4 ${
        // .eng-row-highlight (kept in index.css - the flash keyframe + prefers-reduced-motion
        // static fallback are accessibility/motion behavior, not "look", so they're left as
        // plain CSS rather than reinvented as a Tailwind arbitrary-value animation).
        highlighted ? 'eng-row-highlight' : ''
      }`}
    >
      {/* list-none + a custom marker: <summary>'s native disclosure triangle only renders under
          its default `display: list-item`, which the `flex` layout below already overrides -
          so a hand-drawn one replaces it rather than silently losing the expand/collapse cue. */}
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2 text-sm">
        <span className="inline-block text-muted transition-transform duration-150 group-open:rotate-90" aria-hidden="true">
          &#9656;
        </span>
        <Badge tone={mark.tone ?? 'neutral'}>
          {mark.icon} {e.status}
        </Badge>
        <span className="font-bold">{e.title ?? e.slug}</span>
        <span className="text-xs text-muted">{e.slug}</span>
        {e.outstanding > 0 && <Badge tone="warn">{e.outstanding} outstanding</Badge>}
        {e.pendingRatifications > 0 && <Badge tone="warn">{e.pendingRatifications} ratification(s) pending</Badge>}
        <span className="text-muted">
          {e.opened ?? '-'} &rarr; {e.closed ?? 'open'} {span ? `(${span})` : ''}
        </span>
        {e.costRollup && (
          <Badge
            tone="neutral"
            className="tabular-nums"
            title="🧠 inferred from sessions whose date falls in this engagement's window"
          >
            &#128176; {formatCost(e.costRollup.costUsd, e.costRollup.costPartial)} (
            {e.costRollup.sessionCount} session{e.costRollup.sessionCount === 1 ? '' : 's'})
          </Badge>
        )}
      </summary>
      <div className="mt-3">
        {chips ? (
          <div className="mb-3 flex flex-wrap gap-1">
            {chips.map((c) => (
              <Badge tone="neutral" key={c.label}>
                {c.label}: {c.on ? 'on' : 'off'}
              </Badge>
            ))}
          </div>
        ) : (
          <Badge tone="neutral" className="mb-3">
            settings: not captured
          </Badge>
        )}
        {ccEngagement && ccEngagement.events.length > 0 ? (
          // compact: the row's own <summary> above already carries status/title/dates/cost -
          // the Command Centre's identity block would just repeat it. Its metrics strip (a live
          // Elapsed readout during replay, agents/interactions/loops/tokens/cost at a glance)
          // stays - real information the row doesn't already show.
          <CommandCentre engagement={ccEngagement} compact />
        ) : (
          <p className="mb-0 text-sm text-muted">No timeline yet.</p>
        )}
      </div>
    </details>
  )
}
