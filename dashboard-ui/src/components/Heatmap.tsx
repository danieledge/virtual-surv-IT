import type { Project } from '../lib/types'

interface HeatmapProps {
  projects: Project[]
  maxDays?: number
}

function activityTally(projects: Project[]): Map<string, number> {
  const tally = new Map<string, number>()
  const bump = (date: string | null) => {
    if (!date) return
    tally.set(date, (tally.get(date) ?? 0) + 1)
  }
  for (const p of projects) {
    for (const e of p.engagements) {
      bump(e.opened)
      bump(e.closed)
      for (const a of e.artifacts) bump(a.added)
    }
  }
  return tally
}

// --heat-0..3 aren't wired into tailwind.config.js's color palette (round 1 deliberately left
// --chip-*/--bar-*/--heat-*/--actor-* as plain CSS custom properties, not Tailwind colors), so
// these use Tailwind's arbitrary-value syntax to reference them directly.
const HEAT_BG = ['bg-[var(--heat-0)]', 'bg-[var(--heat-1)]', 'bg-[var(--heat-2)]', 'bg-[var(--heat-3)]']

// Port of scripts/dashboard.py's _heatmap_html()/_activity_tally() - a GitHub-contribution-
// style calendar (weeks = columns, Sun-Sat = rows), capped to the most recent `maxDays` so a
// long-lived portfolio doesn't balloon the grid; the cap is stated on the page, not silent.
export function Heatmap({ projects, maxDays = 120 }: HeatmapProps) {
  const tally = activityTally(projects)
  const parsed = [...tally.entries()]
    .map(([d, count]) => ({ date: new Date(`${d}T00:00:00Z`), count }))
    .filter((e) => !Number.isNaN(e.date.getTime()))
    .sort((a, b) => a.date.getTime() - b.date.getTime())

  if (parsed.length === 0) {
    return <p className="mb-3 text-sm text-muted">No dated activity recorded yet.</p>
  }

  const dayMs = 86400000
  const end = parsed[parsed.length - 1]!.date
  const earliestAllowed = new Date(end.getTime() - (maxDays - 1) * dayMs)
  const start = new Date(Math.max(parsed[0]!.date.getTime(), earliestAllowed.getTime()))
  start.setUTCDate(start.getUTCDate() - start.getUTCDay()) // align grid to a Sunday

  const byDay = new Map<number, number>()
  for (const { date, count } of parsed) {
    if (date.getTime() >= start.getTime()) {
      const key = date.getTime()
      byDay.set(key, (byDay.get(key) ?? 0) + count)
    }
  }

  const totalDays = Math.round((end.getTime() - start.getTime()) / dayMs) + 1
  const cellCount = Math.ceil(totalDays / 7) * 7
  const cells = Array.from({ length: cellCount }, (_, i) => {
    const d = new Date(start.getTime() + i * dayMs)
    const c = byDay.get(d.getTime()) ?? 0
    const level = c === 0 ? 0 : c === 1 ? 1 : c <= 3 ? 2 : 3
    const iso = d.toISOString().slice(0, 10)
    return { iso, level, count: c }
  })

  return (
    <>
      <div className="overflow-x-auto">
        <div
          className="my-3 grid w-max gap-0.5"
          style={{ gridAutoFlow: 'column', gridTemplateRows: 'repeat(7, 11px)' }}
        >
          {cells.map((c) => (
            <div
              key={c.iso}
              className={`h-[11px] w-[11px] rounded-[3px] ${HEAT_BG[c.level]}`}
              title={`${c.iso}: ${c.count} event(s)`}
            />
          ))}
        </div>
      </div>
      <div className="mb-3 mt-1 flex items-center gap-1 text-xs text-muted">
        Less
        {[0, 1, 2, 3].map((lvl) => (
          <div key={lvl} className={`h-[9px] w-[9px] rounded-[3px] ${HEAT_BG[lvl]}`} />
        ))}
        More
      </div>
      <p className="mb-3 text-sm text-muted">
        Each cell = one day (Sun-Sat rows), most recent {maxDays} days of engagement opens/closes
        and artifacts added. Hover a cell for the date.
      </p>
    </>
  )
}
