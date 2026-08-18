import type { Project } from '../lib/types'
import { initialsOf } from '../lib/timelineModel'

interface RosterBarsProps {
  projects: Project[]
  onNavigate: (project: string, slug: string) => void
}

// Same actor-color cycling as the swimlane timeline (TeamSwimlaneTimeline/TimelineStackedList's
// own actorColorVar) - a person's avatar color here is consistent with their lane color there.
function actorColorVar(colorIndex: number): string {
  return `var(--actor-${(colorIndex % 6) + 1})`
}

interface EngagementRef {
  project: string
  slug: string
  title: string | null
}

// Port of scripts/dashboard.py's _roster_bars_html() - tallies `team` ("Name (role-slug)"
// strings) across every known engagement. Plain width-percent bars, no chart library. Each
// bar's engagements are listed as links (onNavigate -> App.goToEngagement) so Portfolio
// doesn't dead-end - this was the "portfolio feels disjointed" fix (2026-08-08).
export function RosterBars({ projects, onNavigate }: RosterBarsProps) {
  const tally = new Map<string, number>()
  const refs = new Map<string, EngagementRef[]>()
  for (const p of projects) {
    for (const e of p.engagements) {
      for (const member of e.team) {
        if (!member) continue
        tally.set(member, (tally.get(member) ?? 0) + 1)
        const list = refs.get(member) ?? []
        list.push({ project: p.name, slug: e.slug, title: e.title })
        refs.set(member, list)
      }
    }
  }
  if (tally.size === 0) {
    return <p className="mb-3 text-sm text-muted">No team attributions recorded yet (set-team).</p>
  }
  const ranked = [...tally.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 20)
  const top = ranked[0]![1]

  return (
    <>
      {ranked.map(([name, count], i) => (
        <div key={name}>
          <div className="my-1.5 flex items-center gap-2 text-sm">
            <span className="flex w-24 shrink-0 items-center gap-2 overflow-hidden sm:w-40 md:w-52">
              <span
                className="inline-flex shrink-0 items-center justify-center rounded-full text-[0.7rem] font-bold text-[var(--actor-text)]"
                style={{ width: 24, height: 24, background: actorColorVar(i) }}
              >
                {initialsOf(name)}
              </span>
              <span className="overflow-hidden text-ellipsis whitespace-nowrap font-semibold">{name}</span>
            </span>
            <div className="h-[0.7rem] flex-1 overflow-hidden rounded-full bg-[var(--bar-track)]">
              <div
                className="h-full rounded-full bg-[var(--bar-fill)]"
                style={{ width: `${Math.round((100 * count) / top)}%` }}
              />
            </div>
            <span className="w-8 text-right font-semibold text-muted">{count}</span>
          </div>
          <div className="mb-2 ml-[6.5rem] flex flex-wrap gap-x-2 gap-y-0.5 text-xs text-muted sm:ml-[10.5rem] md:ml-[13.5rem]">
            {(refs.get(name) ?? []).map((r, i) => (
              <span key={`${r.project}-${r.slug}`}>
                {i > 0 && ' · '}
                <button
                  className="font-semibold text-accent hover:underline"
                  onClick={() => onNavigate(r.project, r.slug)}
                >
                  {r.title ?? r.slug}
                </button>
              </span>
            ))}
          </div>
        </div>
      ))}
    </>
  )
}
