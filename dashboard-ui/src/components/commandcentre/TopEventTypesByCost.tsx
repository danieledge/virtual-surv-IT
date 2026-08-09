import type { CcEngagement, CcEventType } from '../../lib/commandCentre/types'
import { EVENT_TYPE_META, toneVar } from './ccVisuals'
import { CcCollapsible } from './CcCollapsible'

export interface TopEventTypesByCostProps {
  engagement: CcEngagement
}

// Groups engagement.events by type and ranks by summed cost - every figure derived at render
// time, never hardcoded. Colored by the same EVENT_TYPE_META tone used for badges/blocks/pulse
// icons elsewhere in this view, so a given event type reads as the same color everywhere.
export function TopEventTypesByCost({ engagement }: TopEventTypesByCostProps) {
  const costByType = new Map<CcEventType, number>()
  for (const event of engagement.events) {
    costByType.set(event.type, (costByType.get(event.type) ?? 0) + (event.cost ?? 0))
  }
  const totalCost = engagement.events.reduce((sum, e) => sum + (e.cost ?? 0), 0)
  const ranked = [...costByType.entries()].filter(([, cost]) => cost > 0).sort((a, b) => b[1] - a[1])
  const maxCost = ranked.length > 0 ? ranked[0]![1] : 1

  if (ranked.length === 0) {
    return (
      <section className="cc-panel" aria-label="Top event types by cost">
        <h2 className="cc-panel-title">Top Event Types by Cost</h2>
        <p className="cc-empty-state">No costed events recorded yet.</p>
      </section>
    )
  }

  const topLabel = EVENT_TYPE_META[ranked[0]![0]].label
  const topCost = ranked[0]![1]

  return (
    <CcCollapsible
      ariaLabel="Top event types by cost"
      title="Top Event Types by Cost"
      peek={
        <>
          Top: {topLabel} (${topCost.toFixed(2)})
        </>
      }
    >
      <ol className="cc-top-types">
        {ranked.map(([type, cost]) => {
          const meta = EVENT_TYPE_META[type]
          const barPct = (cost / maxCost) * 100
          const sharePct = totalCost > 0 ? (cost / totalCost) * 100 : 0
          return (
            <li className="cc-top-types-row" key={type}>
              <span className="cc-top-types-swatch" style={{ background: toneVar(meta.tone) }} aria-hidden="true" />
              <span className="cc-top-types-label">{meta.label}</span>
              <span className="cc-top-types-bar-track">
                <span
                  className="cc-top-types-bar-fill"
                  style={{ width: `${barPct}%`, background: toneVar(meta.tone) }}
                />
              </span>
              <span className="cc-top-types-amount">${cost.toFixed(2)}</span>
              <span className="cc-top-types-pct">{sharePct.toFixed(0)}%</span>
            </li>
          )
        })}
      </ol>
    </CcCollapsible>
  )
}
