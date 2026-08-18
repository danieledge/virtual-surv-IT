import type { CostByModelRow } from '../lib/types'
import { formatCost, formatNumber } from '../lib/format'

interface CostByModelTableProps {
  rows: CostByModelRow[]
}

const TH = 'border-b-2 border-border-strong bg-surface-1 px-2 py-1.5 sm:px-3 sm:py-2 text-left font-bold text-fg'
const TH_NUM = `${TH} text-right tabular-nums`
const TD_NUM = 'border-b border-border px-2 py-1.5 sm:px-3 sm:py-2 text-right align-top tabular-nums'

// Port of scripts/dashboard.py's _cost_by_model_rows() - machine-wide (every known session,
// not capped like the grouped table below) breakdown by model. The "unknown" row is real
// tokens with a floor cost of $0 (no model field on that message - scripts/dashboard.py's
// _price_usage has nothing to price against), called out rather than folded silently into
// the total (2026-08-08, per-model cost breakdown feedback).
export function CostByModelTable({ rows }: CostByModelTableProps) {
  if (rows.length === 0) {
    return <p className="mb-3 text-sm text-muted">No priced usage found in any known session transcript.</p>
  }
  const grandCost = rows.reduce((sum, r) => sum + r.costUsd, 0)
  return (
    <>
      <div className="mb-1 overflow-x-auto rounded-lg">
        <table className="w-full min-w-max border-collapse bg-surface-2 text-sm">
          <thead>
            <tr>
              <th className={TH}>Model</th>
              <th className={TH_NUM}>Input</th>
              <th className={TH_NUM}>Output</th>
              <th className={TH_NUM}>Cache read</th>
              <th className={TH_NUM}>Cache write</th>
              <th className={TH_NUM}>Cost (est.)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.model} className="hover:bg-surface-3">
                <td className="border-b border-border px-2 py-1.5 sm:px-3 sm:py-2 align-top">
                  {r.model === 'unknown' ? <span className="text-muted">unknown (unpriced)</span> : r.model}
                </td>
                <td className={TD_NUM}>{formatNumber(r.in)}</td>
                <td className={TD_NUM}>{formatNumber(r.out)}</td>
                <td className={TD_NUM}>{formatNumber(r.cacheRead)}</td>
                <td className={TD_NUM}>{formatNumber(r.cacheWrite)}</td>
                <td className={TD_NUM}>{formatCost(r.costUsd)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th className={TH}>Total</th>
              <th className={TH_NUM}>{formatNumber(rows.reduce((s, r) => s + r.in, 0))}</th>
              <th className={TH_NUM}>{formatNumber(rows.reduce((s, r) => s + r.out, 0))}</th>
              <th className={TH_NUM}>{formatNumber(rows.reduce((s, r) => s + r.cacheRead, 0))}</th>
              <th className={TH_NUM}>{formatNumber(rows.reduce((s, r) => s + r.cacheWrite, 0))}</th>
              <th className={TH_NUM}>{formatCost(grandCost)}</th>
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="mb-3 text-sm text-muted">
        Every known session, machine-wide - not capped to the listed rows below. Cost is a
        list-price estimate; see the note under the session table for caveats.
      </p>
    </>
  )
}
