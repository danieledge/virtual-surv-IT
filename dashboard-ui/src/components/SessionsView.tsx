import type { Project, ProjectUsage, SessionUsage } from '../lib/types'
import { formatDuration, formatNumber, formatCost } from '../lib/format'
import { Card } from './ui/Card'

interface SessionsViewProps {
  usageByProject: Record<string, ProjectUsage>
  projects: Project[]
  onNavigate: (project: string, slug: string) => void
}

const LISTED_CAP = 20 // matches scripts/dashboard.py's own per-project session cap

const TH = 'border-b-2 border-border-strong bg-surface-1 px-2 py-1.5 sm:px-3 sm:py-2 text-left font-bold text-fg'
const TH_NUM = `${TH} text-right tabular-nums`
const TD_NUM = 'border-b border-border px-2 py-1.5 sm:px-3 sm:py-2 text-right align-top tabular-nums'

type GroupedSession = SessionUsage & { project: string }

interface Group {
  project: string
  slug: string | null // null = unattributed (no engagement window contains this session)
  title: string | null
  sessions: GroupedSession[]
}

function groupTotals(sessions: GroupedSession[]) {
  return sessions.reduce(
    (t, s) => ({
      in: t.in + s.in,
      out: t.out + s.out,
      cacheRead: t.cacheRead + s.cacheRead,
      cacheWrite: t.cacheWrite + s.cacheWrite,
      span: t.span + s.spanSeconds,
      cost: t.cost + s.costUsd,
      partial: t.partial || s.costPartial,
    }),
    { in: 0, out: 0, cacheRead: 0, cacheWrite: 0, span: 0, cost: 0, partial: false },
  )
}

// Port of the "Measured token usage & session time" table from scripts/dashboard.py's
// render() - moved to its own tab (not stacked under a single engagement card, see
// docs/adr/ADR-013 revision - this table is ops telemetry, categorically different from
// delivery tracking, and was the literal source of the "long list of sessions and only one
// engagement is confusing" feedback). Rows are grouped under the engagement each session's
// date falls inside (🧠 inferred - scripts/dashboard.py's _match_engagement); a session
// matching no known engagement's window lands in an explicit "Unattributed" group rather
// than disappearing (2026-08-08, cost-scoping feedback).
export function SessionsView({ usageByProject, projects, onNavigate }: SessionsViewProps) {
  const titleBySlug = new Map<string, string | null>() // `${project}::${slug}` -> title
  for (const p of projects) {
    for (const e of p.engagements) {
      titleBySlug.set(`${p.name}::${e.slug}`, e.title)
    }
  }

  let totalUnparsable = 0
  let portfolioSeconds = 0

  const groups = new Map<string, Group>()
  for (const [project, stats] of Object.entries(usageByProject)) {
    totalUnparsable += stats.unparsableFiles
    portfolioSeconds += stats.totalSeconds
    for (const s of stats.sessions.slice(0, LISTED_CAP)) {
      const key = `${project}::${s.engagementSlug ?? ''}`
      let group = groups.get(key)
      if (!group) {
        group = {
          project,
          slug: s.engagementSlug,
          title: s.engagementSlug ? (titleBySlug.get(key) ?? null) : null,
          sessions: [],
        }
        groups.set(key, group)
      }
      group.sessions.push({ ...s, project })
    }
  }

  // Attributed groups first (most recent activity first), Unattributed groups last.
  const ordered = [...groups.values()].sort((a, b) => {
    if ((a.slug === null) !== (b.slug === null)) return a.slug === null ? 1 : -1
    const aDate = a.sessions[0]?.date ?? ''
    const bDate = b.sessions[0]?.date ?? ''
    return bDate.localeCompare(aDate)
  })

  const grand = groupTotals(ordered.flatMap((g) => g.sessions))

  return (
    <Card className="my-4">
      <h3>Measured token usage, session time &amp; estimated cost</h3>
      {ordered.length === 0 ? (
        <p className="mb-3 text-sm text-muted">No session transcripts found for any known project.</p>
      ) : (
        <>
          <div className="mb-1 overflow-x-auto rounded-lg">
            <table className="w-full min-w-max border-collapse bg-surface-2 text-sm">
              <thead>
                <tr>
                  <th className={TH}>Date</th>
                  <th className={TH}>Session</th>
                  <th className={TH_NUM}>Input</th>
                  <th className={TH_NUM}>Output</th>
                  <th className={TH_NUM}>Cache read</th>
                  <th className={TH_NUM}>Cache write</th>
                  <th className={TH_NUM}>Cost (est.)</th>
                  <th className={TH_NUM}>Duration</th>
                </tr>
              </thead>
              {ordered.map((g) => {
                const t = groupTotals(g.sessions)
                const key = `${g.project}::${g.slug ?? ''}`
                return (
                  <tbody key={key}>
                    <tr className="bg-accent-muted">
                      <th
                        colSpan={8}
                        className="border-b border-border px-2 py-1.5 sm:px-3 sm:py-2 text-left text-sm font-bold text-fg"
                      >
                        {g.slug ? (
                          <button
                            className="font-semibold text-accent hover:underline"
                            onClick={() => onNavigate(g.project, g.slug!)}
                          >
                            {g.title ?? g.slug}
                          </button>
                        ) : (
                          <span className="text-muted">Unattributed</span>
                        )}{' '}
                        <span className="font-normal text-muted">
                          ({g.project}) &mdash; {g.sessions.length} session
                          {g.sessions.length === 1 ? '' : 's'}, {formatCost(t.cost, t.partial)}
                        </span>
                      </th>
                    </tr>
                    {g.sessions.map((s) => (
                      <tr key={`${s.project}-${s.session}`} className="hover:bg-surface-3">
                        <td className="border-b border-border px-2 py-1.5 sm:px-3 sm:py-2 align-top">{s.date}</td>
                        <td className="border-b border-border px-2 py-1.5 sm:px-3 sm:py-2 align-top text-muted">
                          {s.session.slice(0, 12)}&hellip;
                        </td>
                        <td className={TD_NUM}>{formatNumber(s.in)}</td>
                        <td className={TD_NUM}>{formatNumber(s.out)}</td>
                        <td className={TD_NUM}>{formatNumber(s.cacheRead)}</td>
                        <td className={TD_NUM}>
                          {formatNumber(s.cacheWrite)}
                          {s.badLines ? <span className="text-warn"> ({s.badLines} unparsed)</span> : null}
                        </td>
                        <td className={TD_NUM}>{formatCost(s.costUsd, s.costPartial)}</td>
                        <td className={TD_NUM}>{formatDuration(s.spanSeconds)}</td>
                      </tr>
                    ))}
                  </tbody>
                )
              })}
              <tfoot>
                <tr>
                  <th colSpan={2} className={TH}>
                    Total (listed sessions)
                  </th>
                  <th className={TH_NUM}>{formatNumber(grand.in)}</th>
                  <th className={TH_NUM}>{formatNumber(grand.out)}</th>
                  <th className={TH_NUM}>{formatNumber(grand.cacheRead)}</th>
                  <th className={TH_NUM}>{formatNumber(grand.cacheWrite)}</th>
                  <th className={TH_NUM}>{formatCost(grand.cost, grand.partial)}</th>
                  <th className={TH_NUM}>{formatDuration(grand.span)}</th>
                </tr>
              </tfoot>
            </table>
          </div>
          <p className="mb-3 text-sm text-muted">
            Active time across ALL known sessions, every listed and unlisted one (not just the
            rows above): {formatDuration(portfolioSeconds)}.
          </p>
        </>
      )}
      {totalUnparsable > 0 && (
        <p className="mt-6 text-xs leading-relaxed text-warn">
          &#9888; {totalUnparsable} transcript file(s) could not be read - their usage is
          missing from the totals above.
        </p>
      )}
      <p className="mt-6 text-xs leading-relaxed text-muted">
        &#128202; Session token counts above are the API&apos;s own usage fields; Duration is
        the sum of consecutive-message gaps under 15 minutes (wider gaps read as
        idle/resumed, not active work, and are excluded) - both machine-wide, from disk
        transcripts, kept separate from each engagement row&apos;s coarse open&rarr;close
        day-span, to avoid differently-sourced numbers reading as a contradiction. Cost is a
        &#128202; <strong>estimate at current list pricing</strong> (excludes negotiated
        discounts and time-limited introductory rates); a trailing &ldquo;+&rdquo; marks a
        total that&apos;s a floor because at least one message used a model outside the
        pricing table. Grouping by engagement is &#129504; <strong>inferred</strong> from
        each session&apos;s date falling inside that engagement&apos;s open&rarr;close
        window - not a hard link. Regenerate with <code>npm run dashboard</code>{' '}
        (dashboard-ui/).
      </p>
    </Card>
  )
}
