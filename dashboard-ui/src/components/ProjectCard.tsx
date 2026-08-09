import { useEffect, useRef } from 'react'
import type { Project } from '../lib/types'
import { fileUrl } from '../lib/links'
import { EngagementRow } from './EngagementRow'
import { Card } from './ui/Card'
import { Badge } from './ui/Badge'

interface ProjectCardProps {
  project: Project
  roleLabels: Record<string, string>
  highlightSlug?: string | null // engagement slug to flash+scroll to, when this card's own
  // project matches App's cross-tab navigation target (see App.goToEngagement)
  forceOpen?: boolean // true while a project search is active and this card matched it - opens
  // the card so the match is actually visible, without fighting the user's own manual state
  // once they clear the search (see the effect below: it only ever opens, never closes).
}

const BASIS_LABEL: Record<Project['basis'], string> = {
  config: 'config',
  fingerprint: 'traces',
  explicit: 'given',
  historical: 'historical',
}

// One project = one collapsed-by-default disclosure ("projects collapsed ... by default",
// 2026-08-09): expand the project to see its engagements (themselves collapsed - see
// EngagementRow), expand an engagement to see its settings/timeline detail. Replaces the old
// always-fully-expanded card, which put every project's entire table + every engagement's full
// timeline on screen at once regardless of how many projects the team had touched.
export function ProjectCard({ project: p, roleLabels, highlightSlug, forceOpen }: ProjectCardProps) {
  const gateOk = p.gateFindings.length === 0
  const mapLabel =
    p.mapPath === null
      ? { text: 'none yet', tone: 'muted' as const }
      : p.mapFindings && p.mapFindings.length > 0
        ? { text: `${p.mapFindings.length} finding(s)`, tone: 'bad' as const }
        : { text: 'healthy', tone: 'ok' as const }

  const detailsRef = useRef<HTMLDetailsElement>(null)

  useEffect(() => {
    if ((highlightSlug || forceOpen) && detailsRef.current) detailsRef.current.open = true
  }, [highlightSlug, forceOpen])

  return (
    <Card className={`my-4 border-l-4 p-0 ${gateOk ? 'border-l-ok' : 'border-l-bad'}`}>
      <details ref={detailsRef} className="group">
        <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2 p-4">
          <span
            className="inline-block text-muted transition-transform duration-150 group-open:rotate-90"
            aria-hidden="true"
          >
            &#9656;
          </span>
          <h3 className="!m-0">
            {p.name}{' '}
            <span className="font-normal text-muted">
              ({BASIS_LABEL[p.basis]} &middot; v{p.version ?? '-'})
            </span>
          </h3>
          <Badge tone="neutral">
            {p.engagements.length} engagement{p.engagements.length === 1 ? '' : 's'}
          </Badge>
          {gateOk ? <Badge tone="ok">DoD PASS</Badge> : <Badge tone="bad">DoD {p.gateFindings.length} finding(s)</Badge>}
          {p.consentOpen && <Badge tone="warn">&#9888; consent open</Badge>}
        </summary>
        <div className="border-t border-border p-4">
          <p className="mb-3 flex flex-wrap gap-1 text-sm text-muted">
            <Badge tone="neutral">docx export: {p.preferences.docx ? 'on' : 'off'}</Badge>
            <Badge tone="neutral">citations: {p.preferences.citations ? 'on' : 'off'}</Badge>
            {p.toolProbe ? (
              <Badge tone="neutral">
                tools: {p.toolProbe.installed}/{p.toolProbe.total}
                {!p.toolProbe.fresh ? ' (stale)' : ''}
              </Badge>
            ) : (
              <Badge tone="neutral">tools: not probed</Badge>
            )}
            {p.hookWiring && (
              <Badge tone="neutral">
                hooks wired: {p.hookWiring.wired}/{p.hookWiring.total}
              </Badge>
            )}
            {p.branch && <Badge tone="neutral">branch: {p.branch}</Badge>}
          </p>
          <div className="mb-1 overflow-x-auto rounded-lg">
            <table className="w-full min-w-max border-collapse bg-surface-2 text-sm">
              <thead>
                <tr>
                  <th className="border-b-2 border-border-strong bg-surface-1 px-2 py-1.5 sm:px-3 sm:py-2 text-left font-bold text-fg">
                    Archived
                  </th>
                  <th className="border-b-2 border-border-strong bg-surface-1 px-2 py-1.5 sm:px-3 sm:py-2 text-left font-bold text-fg">
                    Closing emails
                  </th>
                  <th className="border-b-2 border-border-strong bg-surface-1 px-2 py-1.5 sm:px-3 sm:py-2 text-left font-bold text-fg">
                    Codebase map
                  </th>
                  <th className="border-b-2 border-border-strong bg-surface-1 px-2 py-1.5 sm:px-3 sm:py-2 text-left font-bold text-fg">
                    Exec-consent marker
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr className="hover:bg-surface-3">
                  <td className="border-b border-border px-2 py-1.5 sm:px-3 sm:py-2 text-right align-top tabular-nums">
                    {p.archivedCount}
                  </td>
                  <td className="border-b border-border px-2 py-1.5 sm:px-3 sm:py-2 text-right align-top tabular-nums">
                    {p.emails.length}
                  </td>
                  <td className="border-b border-border px-2 py-1.5 sm:px-3 sm:py-2 align-top">
                    {p.mapPath ? (
                      <a href={fileUrl(p.mapPath) ?? undefined} target="_blank" rel="noopener noreferrer">
                        <span
                          className={
                            mapLabel.tone === 'muted'
                              ? 'text-muted'
                              : mapLabel.tone === 'ok'
                                ? 'font-semibold text-ok'
                                : 'font-semibold text-bad'
                          }
                        >
                          {mapLabel.text}
                        </span>
                      </a>
                    ) : (
                      <span
                        className={
                          mapLabel.tone === 'muted'
                            ? 'text-muted'
                            : mapLabel.tone === 'ok'
                              ? 'font-semibold text-ok'
                              : 'font-semibold text-bad'
                        }
                      >
                        {mapLabel.text}
                      </span>
                    )}
                  </td>
                  <td className="border-b border-border px-2 py-1.5 sm:px-3 sm:py-2 align-top">
                    {p.consentOpen ? (
                      <Badge tone="warn">&#9888; OPEN</Badge>
                    ) : (
                      <span className="text-muted">closed</span>
                    )}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          {p.emails.length > 0 && (
            <details className="mt-1">
              <summary className="cursor-pointer text-sm font-semibold text-muted">
                Closing emails ({p.emails.length})
              </summary>
              <div className="mt-2 flex flex-col gap-1">
                {p.emails.map((email) => (
                  <div key={email.absPath}>
                    <a href={fileUrl(email.absPath) ?? undefined} target="_blank" rel="noopener noreferrer">
                      {email.name}
                    </a>
                  </div>
                ))}
              </div>
            </details>
          )}
          {p.engagements.length === 0 ? (
            <p className="mb-3 mt-3 text-sm text-muted">No engagements yet.</p>
          ) : (
            <div className="mt-3 flex flex-col gap-3">
              {p.engagements.map((e) => (
                <EngagementRow
                  key={e.slug}
                  engagement={e}
                  roleLabels={roleLabels}
                  projectName={p.name}
                  highlighted={highlightSlug === e.slug}
                />
              ))}
            </div>
          )}
          {p.archivedCount > 0 && (
            <p className="mb-0 mt-3 text-sm text-muted">
              + {p.archivedCount} archived (excluded above -{' '}
              <code>engagement_state unarchive &lt;slug&gt;</code> to bring one back into scope).
            </p>
          )}
        </div>
      </details>
    </Card>
  )
}
