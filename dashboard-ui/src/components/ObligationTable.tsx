import type { ObligationRow } from '../lib/types'
import { Badge } from './ui/Badge'

interface ObligationTableProps {
  rows: ObligationRow[]
  onNavigate: (project: string, slug: string) => void
}

// Port of scripts/dashboard.py's _obligation_table_html() - rows are precomputed by Python
// (obligation_coverage(), reusing check_citations' own matcher), this only renders them. The
// "Cited by" column links each source engagement back to its row on the Engagements tab
// (onNavigate -> App.goToEngagement) - Portfolio no longer dead-ends (2026-08-08).
export function ObligationTable({ rows, onNavigate }: ObligationTableProps) {
  if (rows.length === 0) {
    return <p className="mb-3 text-sm text-muted">No pinpoint citations found in any known artifact yet.</p>
  }
  return (
    <>
      <div className="mb-1 overflow-x-auto rounded-lg">
        <table className="w-full min-w-max border-collapse bg-surface-2 text-sm">
          <thead>
            <tr>
              <th className="border-b-2 border-border-strong bg-surface-1 px-2 py-1.5 sm:px-3 sm:py-2 text-left font-bold text-fg">
                Citation
              </th>
              <th className="border-b-2 border-border-strong bg-surface-1 px-2 py-1.5 sm:px-3 sm:py-2 text-right font-bold text-fg tabular-nums">
                Occurrences
              </th>
              <th className="border-b-2 border-border-strong bg-surface-1 px-2 py-1.5 sm:px-3 sm:py-2 text-left font-bold text-fg">
                Cited by
              </th>
              <th className="border-b-2 border-border-strong bg-surface-1 px-2 py-1.5 sm:px-3 sm:py-2 text-left font-bold text-fg">
                Register status
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.citation} className="hover:bg-surface-3">
                <td className="border-b border-border px-2 py-1.5 sm:px-3 sm:py-2 align-top">{r.citation}</td>
                <td className="border-b border-border px-2 py-1.5 sm:px-3 sm:py-2 text-right align-top tabular-nums">{r.count}</td>
                <td className="border-b border-border px-2 py-1.5 sm:px-3 sm:py-2 align-top">
                  {r.sources.map((s, i) => (
                    <span key={`${s.project}-${s.slug ?? i}`}>
                      {i > 0 && ' · '}
                      {s.slug ? (
                        <button
                          className="font-semibold text-accent hover:underline"
                          onClick={() => onNavigate(s.project, s.slug!)}
                        >
                          {s.title ?? s.slug}
                        </button>
                      ) : (
                        (s.title ?? s.project)
                      )}
                    </span>
                  ))}
                </td>
                <td className="border-b border-border px-2 py-1.5 sm:px-3 sm:py-2 align-top">
                  {r.verified ? <Badge tone="ok">verified</Badge> : <Badge tone="warn">unverified</Badge>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mb-3 text-sm text-muted">
        Citations found in every known engagement&apos;s artifacts, matched against
        config/regulatory-register.yaml - the same matcher check_citations.py itself uses.
      </p>
    </>
  )
}
