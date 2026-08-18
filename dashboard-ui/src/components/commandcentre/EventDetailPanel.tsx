import type { CcEngagement, CcEvent, CcEventStatus } from '../../lib/commandCentre/types'
import { formatClock, formatElapsed } from '../../lib/commandCentre/timelineLayout'
import { EVENT_TYPE_META } from './ccVisuals'
import { CcCollapsible } from './CcCollapsible'

export interface EventDetailPanelProps {
  event: CcEvent | null
  engagement: CcEngagement
}

const STATUS_META: Record<CcEventStatus, { label: string; symbol: string; tone: 'success' | 'error' | 'accent' | 'neutral' }> = {
  completed: { label: 'Completed', symbol: '✓', tone: 'success' },
  failed: { label: 'Failed', symbol: '✕', tone: 'error' },
  active: { label: 'Active', symbol: '●', tone: 'accent' },
  waiting: { label: 'Waiting', symbol: '○', tone: 'neutral' },
}

export function EventDetailPanel({ event, engagement }: EventDetailPanelProps) {
  if (!event) {
    return (
      <section className="cc-panel" aria-label="Event detail">
        <h2 className="cc-panel-title">Event Detail</h2>
        <p className="cc-empty-state">Select an event on the timeline or pulse strip to see detail here.</p>
      </section>
    )
  }

  const agent = engagement.agents.find((a) => a.id === event.agentId)
  const target = event.targetAgentId ? engagement.agents.find((a) => a.id === event.targetAgentId) : undefined
  const meta = EVENT_TYPE_META[event.type]
  const statusMeta = STATUS_META[event.status]
  const totalTokens = (event.inputTokens ?? 0) + (event.outputTokens ?? 0)
  const hasTokens = event.inputTokens !== undefined || event.outputTokens !== undefined
  const hasConfidence = event.why?.confidenceBefore !== undefined || event.why?.confidenceAfter !== undefined

  return (
    <CcCollapsible ariaLabel="Event detail" title="Event Detail" peek={event.title}>
      <span className={`cc-badge cc-badge-${meta.tone}`}>{meta.label}</span>
      <h3 className="cc-detail-title">{event.title}</h3>
      {target && (
        <p className="cc-detail-route">
          {agent?.name ?? event.agentId} <span aria-hidden="true">→</span> {target.name}
          <span className="cc-detail-route-time"> · {formatClock(engagement.startClock, event.startedAt)}</span>
        </p>
      )}
      <p className="cc-detail-summary">{event.summary}</p>

      <dl className="cc-detail-meta-grid">
        <div className="cc-detail-meta-item">
          <dt>Type</dt>
          <dd>{meta.label}</dd>
        </div>
        <div className="cc-detail-meta-item">
          <dt>Status</dt>
          <dd className={`cc-status-inline cc-status-inline-${statusMeta.tone}`}>
            {statusMeta.label} {statusMeta.symbol}
          </dd>
        </div>
        <div className="cc-detail-meta-item">
          <dt>Agent</dt>
          <dd>{agent ? `${agent.name} · ${agent.role}` : event.agentId}</dd>
        </div>
        {target && (
          <div className="cc-detail-meta-item">
            <dt>Target</dt>
            <dd>
              {target.name} · {target.role}
            </dd>
          </div>
        )}
        <div className="cc-detail-meta-item">
          <dt>Start</dt>
          <dd>{formatClock(engagement.startClock, event.startedAt)}</dd>
        </div>
        <div className="cc-detail-meta-item">
          <dt>End</dt>
          <dd>{formatClock(engagement.startClock, event.completedAt)}</dd>
        </div>
        <div className="cc-detail-meta-item">
          <dt>Duration</dt>
          <dd>{formatElapsed(event.completedAt - event.startedAt)}</dd>
        </div>
        {event.cost !== undefined && (
          <div className="cc-detail-meta-item">
            <dt>Cost</dt>
            <dd>${event.cost.toFixed(2)}</dd>
          </div>
        )}
        {hasTokens && (
          <div className="cc-detail-meta-item">
            <dt>Tokens</dt>
            <dd>
              {totalTokens.toLocaleString('en-US')}
              <span className="cc-metric-sub">
                {' '}
                ({(event.inputTokens ?? 0).toLocaleString('en-US')} in / {(event.outputTokens ?? 0).toLocaleString('en-US')}{' '}
                out)
              </span>
            </dd>
          </div>
        )}
      </dl>

      {event.why && (
        <div className="cc-why-panel">
          <h3 className="cc-why-title">Why did this happen?</h3>
          <span className="cc-why-gear" aria-hidden="true" title="Reasoning trace">
            ⚙
          </span>
          <dl className="cc-why-list">
            <div className="cc-why-row">
              <span className="cc-why-row-icon" aria-hidden="true">
                ◆
              </span>
              <dt>Trigger</dt>
              <dd>{event.why.trigger}</dd>
            </div>
            {event.why.objective && (
              <div className="cc-why-row">
                <span className="cc-why-row-icon" aria-hidden="true">
                  ▸
                </span>
                <dt>Objective</dt>
                <dd>{event.why.objective}</dd>
              </div>
            )}
            {hasConfidence && (
              <div className="cc-why-row">
                <span className="cc-why-row-icon" aria-hidden="true">
                  ◔
                </span>
                <dt>Confidence</dt>
                <dd className="cc-confidence-shift">
                  {event.why.confidenceBefore !== undefined ? event.why.confidenceBefore.toFixed(2) : '—'}
                  {' → '}
                  {event.why.confidenceAfter !== undefined ? event.why.confidenceAfter.toFixed(2) : '—'}
                </dd>
              </div>
            )}
            <div className="cc-why-row">
              <span className="cc-why-row-icon" aria-hidden="true">
                ✓
              </span>
              <dt>Outcome</dt>
              <dd>{event.why.outcome}</dd>
            </div>
          </dl>
        </div>
      )}
    </CcCollapsible>
  )
}
