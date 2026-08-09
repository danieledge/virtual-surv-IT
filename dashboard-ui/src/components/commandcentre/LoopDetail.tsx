import type { CcEngagement, CcLoop } from '../../lib/commandCentre/types'
import { formatClock, formatElapsed } from '../../lib/commandCentre/timelineLayout'
import { CcCollapsible } from './CcCollapsible'

export interface LoopDetailProps {
  loop: CcLoop | null
  engagement: CcEngagement
}

// Shown in the sidebar in place of EventDetailPanel when a loop arc is clicked on the hero
// timeline - the "rework moment" gets its own dedicated iteration-by-iteration breakdown.
export function LoopDetail({ loop, engagement }: LoopDetailProps) {
  if (!loop) {
    return (
      <section className="cc-panel" aria-label="Loop detail">
        <h2 className="cc-panel-title">Loop Detail</h2>
        <p className="cc-empty-state">Select a loop arc on the timeline to see its rework history here.</p>
      </section>
    )
  }

  // Honestly computed from the engagement's own event costs - never a hardcoded share.
  const engagementCost = engagement.events.reduce((sum, e) => sum + (e.cost ?? 0), 0)
  const pctOfEngagement = engagementCost > 0 ? (loop.cost / engagementCost) * 100 : 0

  return (
    <CcCollapsible
      className="cc-panel-loop"
      ariaLabel="Loop detail"
      title={
        <>
          <span className="cc-badge cc-badge-loop">Loop</span> Loop Detail
        </>
      }
      peek={
        <>
          ${loop.cost.toFixed(2)} · {loop.iterations.length} iteration{loop.iterations.length === 1 ? '' : 's'}
        </>
      }
    >
      <p className="cc-detail-summary">{loop.trigger}</p>

      <dl className="cc-detail-meta-grid">
        <div className="cc-detail-meta-item">
          <dt>Started</dt>
          <dd>{formatClock(engagement.startClock, loop.startedAt)}</dd>
        </div>
        <div className="cc-detail-meta-item">
          <dt>Duration</dt>
          <dd>{formatElapsed(loop.completedAt - loop.startedAt)}</dd>
        </div>
        <div className="cc-detail-meta-item">
          <dt>Tokens</dt>
          <dd>{loop.tokens.toLocaleString('en-US')}</dd>
        </div>
        <div className="cc-detail-meta-item">
          <dt>Cost</dt>
          <dd>${loop.cost.toFixed(2)}</dd>
        </div>
      </dl>

      <div className="cc-loop-ministat-row">
        <div className="cc-loop-ministat">
          <span className="cc-loop-ministat-value">${loop.cost.toFixed(2)}</span>
          <span className="cc-loop-ministat-label">Cost</span>
        </div>
        <div className="cc-loop-ministat">
          <span className="cc-loop-ministat-value">{loop.tokens.toLocaleString('en-US')}</span>
          <span className="cc-loop-ministat-label">Tokens</span>
        </div>
        <div className="cc-loop-ministat">
          <span className="cc-loop-ministat-value">{pctOfEngagement.toFixed(1)}%</span>
          <span className="cc-loop-ministat-label">% of Engagement</span>
        </div>
      </div>

      <h3 className="cc-why-title">Resolution</h3>
      <p className="cc-detail-summary">{loop.resolution}</p>

      <h3 className="cc-why-title">Iterations</h3>
      <ol className="cc-loop-iterations">
        {loop.iterations.map((iteration, i) => {
          const event = engagement.events.find((e) => e.id === iteration.eventId)
          const agent = event ? engagement.agents.find((a) => a.id === event.agentId) : undefined
          return (
            <li className="cc-loop-iteration" key={iteration.eventId}>
              <span className="cc-loop-iteration-number">{i + 1}</span>
              <span className="cc-loop-iteration-body">
                <span className="cc-loop-iteration-label">{iteration.label}</span>
                <span className="cc-loop-iteration-detail">{iteration.detail}</span>
                {agent && <span className="cc-loop-iteration-agent">{agent.name}</span>}
              </span>
            </li>
          )
        })}
      </ol>
    </CcCollapsible>
  )
}
