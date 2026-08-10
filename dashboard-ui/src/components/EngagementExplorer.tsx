import { useEffect, useMemo, useRef, useState } from 'react'
import type { Engagement, Project } from '../lib/types'
import { STATUS_MARK, daySpan, settingsChips } from '../lib/engagement'
import { formatCost } from '../lib/format'
import { engagementAnchorId } from '../lib/links'
import { buildCcEngagementFromReal } from '../lib/commandCentre/fromReal'
import { agentColorVar } from './commandcentre/ccVisuals'
import { CommandCentre } from './commandcentre/CommandCentre'
import { Badge } from './ui/Badge'

interface EngagementExplorerProps {
  projects: Project[]
  roleLabels: Record<string, string>
  navTarget: { project: string; slug: string } | null
  onNavConsumed: () => void
}

type StatusFilter = 'All' | 'Open' | 'Blocked' | 'Closed'
const STATUS_FILTERS: StatusFilter[] = ['All', 'Open', 'Blocked', 'Closed']
const NARROW_QUERY = '(max-width: 760px)'

const BASIS_LABEL: Record<Project['basis'], string> = {
  config: 'config',
  fingerprint: 'traces',
  explicit: 'given',
  historical: 'historical',
}

interface FlatRow {
  project: Project
  engagement: Engagement
}

function rowKey(project: string, slug: string): string {
  return `${project}/${slug}`
}

function matchesStatusFilter(status: Engagement['status'], filter: StatusFilter): boolean {
  if (filter === 'All') return true
  if (filter === 'Open') return status === 'in_progress' || status === 'closing'
  if (filter === 'Blocked') return status === 'blocked'
  return status === 'closed'
}

const TONE_DOT: Record<string, string> = { ok: 'var(--ok)', warn: 'var(--warn)', bad: 'var(--bad)' }
function statusDotColor(status: Engagement['status']): string {
  const tone = STATUS_MARK[status]?.tone
  return tone ? TONE_DOT[tone]! : 'var(--muted)'
}

/** Most-recently-opened row, by `opened` (ISO date strings compare correctly as plain
 * strings) - same "pick the freshest thing" default the old top-level Command Centre picker
 * used, ported here since this view now owns the same job. */
function defaultRowKey(rows: FlatRow[]): string | null {
  if (rows.length === 0) return null
  const dated = rows.filter((r) => r.engagement.opened)
  const chosen =
    dated.length > 0
      ? dated.reduce((latest, r) => (r.engagement.opened! > latest.engagement.opened! ? r : latest))
      : rows[0]!
  return rowKey(chosen.project.name, chosen.engagement.slug)
}

// Master-detail Engagements view (2026-08-09, replacing per-project nested disclosures - a
// design draft pulled from claude.ai/design made the same call independently: "pick an
// engagement from a searchable list, see its full detail in one place" scales better than an
// accordion tree once there's more than a handful of engagements. Layout/IA (search, status
// filter chips, project-grouped list, list/detail split on narrow viewports) is taken from
// that draft; the detail pane keeps this app's own real Command Centre (swimlane, pulse,
// replay, event/loop sidebar) rather than the draft's flattened static mockup of one - the
// draft was necessarily built without real interaction wiring behind it, and trading real
// capability for a sketch would be a regression, not a redesign.
export function EngagementExplorer({ projects, roleLabels, navTarget, onNavConsumed }: EngagementExplorerProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('All')
  const [narrow, setNarrow] = useState(false)
  const [view, setView] = useState<'list' | 'detail'>('list')

  const allRows = useMemo<FlatRow[]>(
    () => projects.flatMap((project) => project.engagements.map((engagement) => ({ project, engagement }))),
    [projects],
  )

  const [selectedKey, setSelectedKey] = useState<string | null>(() => defaultRowKey(allRows))

  useEffect(() => {
    const mq = window.matchMedia(NARROW_QUERY)
    const onChange = () => setNarrow(mq.matches)
    onChange()
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  // Cross-tab nav (Portfolio/Sessions -> here): select directly, no more DOM scroll+flash
  // hack - selection itself is now the visible feedback (the row highlights, the detail pane
  // updates), so there's nothing left to fake with a CSS animation.
  useEffect(() => {
    if (!navTarget) return
    setSelectedKey(rowKey(navTarget.project, navTarget.slug))
    setView('detail')
    rootRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    onNavConsumed()
  }, [navTarget, onNavConsumed])

  const q = query.trim().toLowerCase()
  const visibleRows = useMemo(
    () =>
      allRows.filter(
        (r) =>
          matchesStatusFilter(r.engagement.status, statusFilter) &&
          (!q || `${r.engagement.title ?? ''} ${r.engagement.slug} ${r.project.name}`.toLowerCase().includes(q)),
      ),
    [allRows, statusFilter, q],
  )

  const groups = useMemo(() => {
    const byProject = new Map<string, FlatRow[]>()
    for (const row of visibleRows) {
      const list = byProject.get(row.project.name) ?? []
      list.push(row)
      byProject.set(row.project.name, list)
    }
    return projects.filter((p) => byProject.has(p.name)).map((p) => ({ project: p, rows: byProject.get(p.name)! }))
  }, [projects, visibleRows])

  const selected =
    (selectedKey && allRows.find((r) => rowKey(r.project.name, r.engagement.slug) === selectedKey)) ||
    allRows[0] ||
    null

  const ccEngagement = useMemo(
    () => (selected ? buildCcEngagementFromReal(selected.engagement, selected.project.name, roleLabels) : null),
    [selected, roleLabels],
  )

  function selectRow(project: string, slug: string) {
    setSelectedKey(rowKey(project, slug))
    if (narrow) setView('detail')
  }

  if (projects.length === 0) {
    return <p className="text-muted">No team projects found.</p>
  }
  if (allRows.length === 0) {
    return <p className="text-muted">No engagements yet across any project.</p>
  }

  const showList = !narrow || view === 'list'
  const showDetail = !narrow || view === 'detail'

  return (
    <div
      ref={rootRef}
      className="-mx-3 mt-2 flex flex-wrap items-start overflow-hidden rounded-2xl border border-border bg-surface-2 scroll-mt-4 sm:-mx-6 md:mx-0"
    >
      {showList && (
        <aside className="flex min-w-[270px] flex-1 basis-[300px] flex-col self-stretch border-border sm:max-w-[380px] sm:border-r">
          <div className="flex flex-col gap-2.5 border-b border-border p-4">
            <label className="block">
              <span className="sr-only">Search projects and engagements</span>
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search projects or engagements…"
                className="w-full rounded-lg border border-border bg-surface-1 px-3 py-2 text-sm text-fg placeholder:text-muted focus:border-border-strong focus:outline-none"
              />
            </label>
            <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by status">
              {STATUS_FILTERS.map((f) => (
                <button
                  key={f}
                  type="button"
                  aria-pressed={statusFilter === f}
                  onClick={() => setStatusFilter(f)}
                  className={`rounded-full border px-3 py-1 text-xs font-semibold transition-colors duration-150 ${
                    statusFilter === f
                      ? 'border-accent bg-accent text-[var(--actor-text)]'
                      : 'border-border text-muted hover:text-fg'
                  }`}
                >
                  {f}
                </button>
              ))}
            </div>
          </div>
          <div className="flex flex-col">
            {groups.length === 0 ? (
              <p className="p-4 text-sm text-muted">No project or engagement matches this filter.</p>
            ) : (
              groups.map(({ project, rows }) => (
                <div key={project.path}>
                  <div className="flex flex-wrap items-center gap-2 border-b border-border bg-surface-1 px-4 py-2.5">
                    <span className="text-sm font-bold">{project.name}</span>
                    <span className="font-mono text-[10.5px] text-muted">
                      {BASIS_LABEL[project.basis]} &middot; v{project.version ?? '-'}
                      {project.branch ? ` · branch ${project.branch}` : ''}
                    </span>
                    <span className="ml-auto flex gap-1.5">
                      {project.consentOpen && <Badge tone="warn">&#9888; consent open</Badge>}
                      <Badge tone={project.gateFindings.length === 0 ? 'ok' : 'bad'}>
                        {project.gateFindings.length === 0 ? 'DoD PASS' : `DoD ${project.gateFindings.length}`}
                      </Badge>
                    </span>
                  </div>
                  {rows.map(({ engagement: e }) => {
                    const isSelected = selected?.project.name === project.name && selected.engagement.slug === e.slug
                    return (
                      <button
                        key={e.slug}
                        id={engagementAnchorId(project.name, e.slug)}
                        type="button"
                        aria-current={isSelected ? 'true' : undefined}
                        onClick={() => selectRow(project.name, e.slug)}
                        className={`flex w-full scroll-mt-4 flex-col gap-1 border-b border-l-[3px] border-border px-4 py-3.5 text-left font-sans text-fg transition-colors duration-150 ${
                          isSelected ? 'border-l-accent bg-surface-2' : 'border-l-transparent hover:bg-surface-1'
                        }`}
                      >
                        <span className="flex items-center gap-2">
                          <span
                            className="h-[7px] w-[7px] shrink-0 rounded-full"
                            style={{ background: statusDotColor(e.status) }}
                            aria-hidden="true"
                          />
                          <span className="text-sm font-semibold">{e.title ?? e.slug}</span>
                        </span>
                        <span className="flex justify-between gap-3 pl-[15px] font-mono text-[11px] text-muted">
                          <span>{e.slug}</span>
                          <span className="tabular-nums">
                            {e.costRollup ? formatCost(e.costRollup.costUsd, e.costRollup.costPartial) : '-'}
                          </span>
                        </span>
                        <span className="pl-[15px] font-mono text-[11px] text-muted">
                          {daySpan(e.opened, e.closed) ?? 'no dates'}
                          {e.outstanding > 0 ? ` · ${e.outstanding} outstanding` : ''}
                        </span>
                      </button>
                    )
                  })}
                </div>
              ))
            )}
          </div>
        </aside>
      )}

      {showDetail && selected && ccEngagement && (
        <main className="flex min-w-[320px] flex-[999_1_560px] flex-col">
          {narrow && (
            <button
              type="button"
              onClick={() => setView('list')}
              className="flex items-center gap-2 border-b border-border bg-surface-1 px-4 py-3 text-left text-sm font-semibold text-accent"
            >
              &lsaquo; All engagements
            </button>
          )}
          {/* Only what CommandCentre's own header doesn't already show (title/status/id/type,
              metrics strip) - date range, who's on it, and this engagement's settings snapshot. */}
          <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3 sm:px-6">
            <span className="font-mono text-[11.5px] text-muted">
              {selected.engagement.opened ?? '-'} &rarr; {selected.engagement.closed ?? 'open'}
              {daySpan(selected.engagement.opened, selected.engagement.closed)
                ? ` (${daySpan(selected.engagement.opened, selected.engagement.closed)})`
                : ''}
            </span>
            {ccEngagement.agents.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {ccEngagement.agents.map((a) => (
                  <span
                    key={a.id}
                    className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-1 py-0.5 pl-1 pr-2.5 text-xs"
                  >
                    <span
                      className="flex h-[18px] w-[18px] items-center justify-center rounded-full text-[9.5px] font-bold text-[var(--actor-text)]"
                      style={{ background: agentColorVar(a.colorIndex) }}
                    >
                      {a.name.slice(0, 2).toUpperCase()}
                    </span>
                    {a.name} <span className="font-mono text-[10.5px] text-muted">{a.role}</span>
                  </span>
                ))}
              </div>
            )}
            {(() => {
              const chips = settingsChips(selected.engagement.settingsSnapshot)
              return chips ? (
                <div className="ml-auto flex flex-wrap gap-1.5">
                  {chips.map((c) => (
                    <span
                      key={c.label}
                      className="rounded-full border border-border bg-surface-1 px-2.5 py-1 font-mono text-[11px] text-muted"
                    >
                      {c.label}: {c.on ? 'on' : 'off'}
                    </span>
                  ))}
                </div>
              ) : null
            })()}
          </div>
          <CommandCentre engagement={ccEngagement} />
        </main>
      )}
    </div>
  )
}
