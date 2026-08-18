import type { Project, ObligationRow, ProjectUsage } from '../lib/types'
import { formatCost } from '../lib/format'
import { StatTile, type StatTileTone } from './ui/StatTile'
import { useDefaultOpen } from '../hooks/useDefaultOpen'

interface KpiStripProps {
  projects: Project[]
  obligations: ObligationRow[]
  usageByProject: Record<string, ProjectUsage>
}

interface Tile {
  icon: string
  label: string
  value: string | number
  tone?: StatTileTone
}

// Mirrors scripts/dashboard.py's _kpi_strip_html() tile-for-tile - the executive-summary
// read, before anyone opens a single table. All figures are straight counts off data
// already collected (📊 observed).
export function KpiStrip({ projects, obligations, usageByProject }: KpiStripProps) {
  const engagements = projects.flatMap((p) => p.engagements)
  const statusCounts = new Map<string, number>()
  for (const e of engagements) {
    statusCounts.set(e.status, (statusCounts.get(e.status) ?? 0) + 1)
  }
  const totalArtifacts = engagements.reduce((sum, e) => sum + e.artifacts.length, 0)
  const teamMembers = new Set(engagements.flatMap((e) => e.team).filter(Boolean))
  const gateClean = projects.filter((p) => p.gateFindings.length === 0).length

  let totalCost = 0
  let costPartial = false
  let totalIn = 0
  let totalCacheRead = 0
  for (const stats of Object.values(usageByProject)) {
    for (const s of stats.sessions) {
      totalCost += s.costUsd
      costPartial = costPartial || s.costPartial
      totalIn += s.in
      totalCacheRead += s.cacheRead
    }
  }
  // Share of input tokens served from cache rather than processed fresh - cache_write (a
  // one-time cost to CREATE a cache entry) is deliberately excluded from the denominator,
  // since it isn't a "miss" in the same sense an uncached input token is.
  const cacheEligible = totalIn + totalCacheRead
  const cacheHitRate = cacheEligible > 0 ? (100 * totalCacheRead) / cacheEligible : null

  const closed = statusCounts.get('closed') ?? 0
  const blocked = statusCounts.get('blocked') ?? 0
  const inProgress = (statusCounts.get('in_progress') ?? 0) + (statusCounts.get('closing') ?? 0)

  // Headline: scale (Projects/Engagements) + the one status actively worth flagging at a
  // glance (Blocked - Closed/In progress are informational, not actionable) + the number most
  // likely to matter on a quick check-in (Est. cost). Everything else is real but secondary -
  // collapsed by default on phone rather than pushing every other section further down the
  // page (2026-08-09 live feedback: "too many top level metrics").
  const headline: Tile[] = [
    { icon: '📁', label: 'Projects', value: projects.length },
    { icon: '🤝', label: 'Engagements', value: engagements.length },
    { icon: '⛔', label: 'Blocked', value: blocked, tone: blocked ? 'warn' : undefined },
    { icon: '💰', label: 'Est. cost', value: formatCost(totalCost, costPartial) },
  ]
  const details: Tile[] = [
    { icon: '✅', label: 'Closed', value: closed, tone: closed ? 'ok' : undefined },
    { icon: '⏳', label: 'In progress', value: inProgress },
    { icon: '📎', label: 'Artifacts', value: totalArtifacts },
    { icon: '👥', label: 'Team members', value: teamMembers.size },
    { icon: '📜', label: 'Obligations cited', value: obligations.length },
    {
      icon: '♻️',
      label: 'Cache hit rate',
      value: cacheHitRate === null ? '-' : `${cacheHitRate.toFixed(0)}%`,
    },
    {
      icon: '🧭',
      label: 'DoD-clean projects',
      value: projects.length ? `${gateClean}/${projects.length}` : '0/0',
      tone: projects.length ? (gateClean === projects.length ? 'ok' : 'warn') : undefined,
    },
  ]
  const defaultOpen = useDefaultOpen()

  return (
    <div className="my-5">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 sm:gap-3 md:grid-cols-4">
        {headline.map((t) => (
          <StatTile key={t.label} icon={t.icon} label={t.label} value={t.value} tone={t.tone ?? 'accent'} />
        ))}
      </div>
      <details className="group mt-2" open={defaultOpen}>
        <summary className="cursor-pointer list-none text-sm font-semibold text-muted [&::-webkit-details-marker]:hidden">
          <span aria-hidden="true" className="inline-block transition-transform duration-150 group-open:rotate-90">
            ▸
          </span>{' '}
          More metrics ({details.length})
        </summary>
        <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3 sm:gap-3 md:grid-cols-4 lg:grid-cols-7">
          {details.map((t) => (
            <StatTile key={t.label} icon={t.icon} label={t.label} value={t.value} tone={t.tone ?? 'accent'} />
          ))}
        </div>
      </details>
    </div>
  )
}
