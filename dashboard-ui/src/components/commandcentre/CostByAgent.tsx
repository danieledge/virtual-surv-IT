import type { CcEngagement } from '../../lib/commandCentre/types'
import { agentColorVar, formatCompact } from './ccVisuals'
import { CcCollapsible } from './CcCollapsible'

export interface CostByAgentProps {
  engagement: CcEngagement
}

// Every figure here is derived from engagement.events at render time - never a hardcoded
// headline total. Title says USD (not the reference mockup's GBP) to stay consistent with the
// $ formatting already used everywhere else in this view (EventDetailPanel, LoopDetail, the
// header strip).
export function CostByAgent({ engagement }: CostByAgentProps) {
  const costByAgent = new Map<string, number>()
  for (const event of engagement.events) {
    costByAgent.set(event.agentId, (costByAgent.get(event.agentId) ?? 0) + (event.cost ?? 0))
  }
  const totalCost = engagement.agents.reduce((sum, a) => sum + (costByAgent.get(a.id) ?? 0), 0)

  let totalInputTokens = 0
  let totalOutputTokens = 0
  for (const event of engagement.events) {
    totalInputTokens += event.inputTokens ?? 0
    totalOutputTokens += event.outputTokens ?? 0
  }
  const totalTokens = totalInputTokens + totalOutputTokens
  const inputPct = totalTokens > 0 ? (totalInputTokens / totalTokens) * 100 : 0
  const outputPct = totalTokens > 0 ? 100 - inputPct : 0

  return (
    <CcCollapsible ariaLabel="Cost by agent" title="Cost (USD)" peek={`$${totalCost.toFixed(2)} total`}>
      <p className="cc-cost-total">${totalCost.toFixed(2)}</p>

      <div className="cc-cost-stacked-bar" role="img" aria-label="Cost share by agent">
        {engagement.agents.map((agent) => {
          const cost = costByAgent.get(agent.id) ?? 0
          const pct = totalCost > 0 ? (cost / totalCost) * 100 : 0
          if (pct <= 0) return null
          return (
            <span
              key={agent.id}
              className="cc-cost-stacked-segment"
              style={{ width: `${pct}%`, background: agentColorVar(agent.colorIndex) }}
              title={`${agent.name}: $${cost.toFixed(2)}`}
            />
          )
        })}
      </div>

      <ul className="cc-cost-legend">
        {engagement.agents.map((agent) => {
          const cost = costByAgent.get(agent.id) ?? 0
          const pct = totalCost > 0 ? (cost / totalCost) * 100 : 0
          return (
            <li className="cc-cost-legend-row" key={agent.id}>
              <span
                className="cc-cost-legend-swatch"
                style={{ background: agentColorVar(agent.colorIndex) }}
                aria-hidden="true"
              />
              <span className="cc-cost-legend-name">{agent.name}</span>
              <span className="cc-cost-legend-amount">${cost.toFixed(2)}</span>
              <span className="cc-cost-legend-pct">{pct.toFixed(0)}%</span>
            </li>
          )
        })}
      </ul>

      <div className="cc-token-breakdown">
        <h3 className="cc-panel-subtitle">Tokens</h3>
        <p className="cc-cost-total cc-cost-total-tokens">{formatCompact(totalTokens)}</p>
        <div className="cc-token-stacked-bar" role="img" aria-label="Input vs output token split">
          <span
            className="cc-token-segment cc-token-segment-input"
            style={{ width: `${inputPct}%` }}
            title={`Input: ${totalInputTokens.toLocaleString('en-US')} tokens`}
          />
          <span
            className="cc-token-segment cc-token-segment-output"
            style={{ width: `${outputPct}%` }}
            title={`Output: ${totalOutputTokens.toLocaleString('en-US')} tokens`}
          />
        </div>
        <p className="cc-token-breakdown-caption">
          Input {inputPct.toFixed(0)}% · Output {outputPct.toFixed(0)}%
        </p>
      </div>
    </CcCollapsible>
  )
}
