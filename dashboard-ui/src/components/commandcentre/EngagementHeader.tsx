import type { CcEngagement } from '../../lib/commandCentre/types'
import { formatElapsed } from '../../lib/commandCentre/timelineLayout'
import { formatCost } from '../../lib/format'
import { formatCompact } from './ccVisuals'

export interface EngagementHeaderProps {
  engagement: CcEngagement
  currentTime: number
  // See CommandCentre's own `compact` doc comment - skips the name/status/started/ID block when
  // a parent already shows it, keeps the metrics strip (the one part that's genuinely additive).
  hideIdentity?: boolean
}

const STATUS_LABEL: Record<CcEngagement['status'], string> = {
  investigating: 'Investigating',
  resolved: 'Resolved',
  blocked: 'Blocked',
}

const RING_RADIUS = 15.5
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS

const INFERRED_COST_TITLE = "🧠 inferred from sessions whose date falls in this engagement's window"

/** Confidence ring color band - purely a display convention for this gauge (not a detection
 * threshold, so it doesn't need the rule-engineering "document rationale + tuning date"
 * treatment): >=0.75 reads as healthy, >=0.5 as developing, below that as low-confidence. */
function confidenceTone(confidence: number): string {
  if (confidence >= 0.75) return 'var(--ok)'
  if (confidence >= 0.5) return 'var(--accent)'
  return 'var(--bad)'
}

// Dense operational readout strip, not dashboard tiles - every figure here is computed from
// engagement.events at render time (never hardcoded), including during replay where Elapsed
// visibly ticks against currentTime.
export function EngagementHeader({ engagement, currentTime, hideIdentity = false }: EngagementHeaderProps) {
  const hasConfidence = engagement.confidence !== undefined
  const hasRealCost = engagement.realCostRollup !== undefined

  // Real events never carry cost/tokens (see lib/commandCentre/fromReal.ts) - this sum is an
  // honest zero for a real engagement with no realCostRollup, and the fixture's real per-event
  // total otherwise. `realCostRollup` (a real, already-computed whole-engagement total one level
  // up) is preferred over this sum whenever it's present, per the plan this was built from.
  const eventCostTotal = engagement.events.reduce((sum, e) => sum + (e.cost ?? 0), 0)
  const eventTokenTotal = engagement.events.reduce((sum, e) => sum + (e.inputTokens ?? 0) + (e.outputTokens ?? 0), 0)
  const totalCost = hasRealCost ? engagement.realCostRollup!.costUsd : eventCostTotal
  const totalTokens = hasRealCost ? engagement.realCostRollup!.tokensIn + engagement.realCostRollup!.tokensOut : eventTokenTotal

  const confidencePct = hasConfidence ? Math.round(engagement.confidence! * 100) : 0
  const ringOffset = hasConfidence ? RING_CIRCUMFERENCE * (1 - engagement.confidence!) : RING_CIRCUMFERENCE
  const ringColor = hasConfidence ? confidenceTone(engagement.confidence!) : 'var(--muted)'

  // Tokens/cost "per minute" trend - derived from real totals over the elapsed window (the
  // replay position if the engagement has been played/seeked into, otherwise the full
  // duration). Never an invented rate. Suppressed whenever the headline totals come from a
  // whole-engagement rollup (not a per-event sum): the plan this was built from called this out
  // for multi-day spans specifically ("a whole-engagement total divided by a multi-day span
  // produces a technically-correct but practically meaningless per-minute figure"), but the same
  // failure is actually WORSE, and far more common, for a same-day-only real engagement - real
  // day-granular data very often has every event land on one calendar day, so
  // `durationSeconds` floors near 0, and totalCost/totalTokens divided by a near-zero window
  // spikes into a nonsense per-minute rate (confirmed live: a real single-day engagement showed
  // "$162,152.22/min" off a $2,702.54 total). A whole-engagement lump total was never metered
  // per-minute in the first place, so this suppresses the trend for ANY realCostRollup-backed
  // total, not only the multi-day case the plan named - broader than the plan's literal
  // wording, kept narrow to real-rollup totals only so the fixture-style per-event-sum path
  // (durationSeconds legitimately reflecting real elapsed replay time) is untouched.
  const showTrend = !hasRealCost
  const elapsedForRate = currentTime > 0 ? currentTime : engagement.durationSeconds
  const minutesElapsed = Math.max(elapsedForRate / 60, 1 / 60)
  const tokensPerMin = totalTokens / minutesElapsed
  const costPerMin = totalCost / minutesElapsed

  return (
    <header className="cc-header">
      {!hideIdentity && (
        <div className="cc-header-top">
          <div className="cc-header-id">
            <span className="cc-header-eyebrow">{engagement.id}</span>
            <div className="cc-header-name-row">
              <h1 className="cc-header-name">{engagement.name}</h1>
              <span className={`cc-status-pill cc-status-${engagement.status}`}>{STATUS_LABEL[engagement.status]}</span>
            </div>
            <span className="cc-header-meta">Type: {engagement.type}</span>
          </div>

          <div className="cc-header-subcard">
            <span className="cc-header-subcard-menu" aria-hidden="true">
              ⋯
            </span>
            <div className="cc-header-subcard-row">
              <span className="cc-header-subcard-label">Started</span>
              {/* No "Today," prefix - a real engagement's day-granular open date is very often
                  not today (see lib/commandCentre/fromReal.ts's own note on startClock being a
                  fixed, honest midnight anchor, not a real timestamp). */}
              <span className="cc-header-subcard-value">{engagement.startClock}</span>
            </div>
            <div className="cc-header-subcard-row">
              <span className="cc-header-subcard-label">ID</span>
              <span className="cc-header-subcard-value">{engagement.id}</span>
            </div>
          </div>
        </div>
      )}

      <dl className="cc-metrics-strip">
        <div className="cc-metric">
          <dt>Elapsed</dt>
          <dd>
            {formatElapsed(currentTime)}
            <span className="cc-metric-sub"> / {formatElapsed(engagement.durationSeconds)}</span>
          </dd>
        </div>
        <div className="cc-metric">
          <dt>Agents</dt>
          <dd>{engagement.agents.length}</dd>
        </div>
        <div className="cc-metric">
          <dt>Interactions</dt>
          <dd>{engagement.events.length}</dd>
        </div>
        <div className="cc-metric">
          <dt>Loops</dt>
          <dd>{engagement.loops.length}</dd>
        </div>
        <div className="cc-metric">
          <dt>Tokens</dt>
          <dd title={hasRealCost ? INFERRED_COST_TITLE : undefined}>
            {totalTokens.toLocaleString('en-US')}
            {hasRealCost && <span className="cc-metric-sub"> 🧠</span>}
          </dd>
          {showTrend && <span className="cc-metric-trend">↗ {formatCompact(tokensPerMin)}/min</span>}
        </div>
        <div className="cc-metric">
          <dt>Cost</dt>
          <dd title={hasRealCost ? INFERRED_COST_TITLE : undefined}>
            {hasRealCost ? formatCost(engagement.realCostRollup!.costUsd, engagement.realCostRollup!.costPartial) : `$${totalCost.toFixed(2)}`}
            {hasRealCost && <span className="cc-metric-sub"> 🧠</span>}
          </dd>
          {showTrend && <span className="cc-metric-trend">↗ ${costPerMin.toFixed(2)}/min</span>}
        </div>
        {hasConfidence && (
          <div className="cc-metric cc-metric-confidence">
            <dt>Confidence</dt>
            <dd>
              <span className="cc-confidence-gauge" role="img" aria-label={`Confidence ${confidencePct}%`}>
                <svg viewBox="0 0 36 36" className="cc-confidence-ring-svg">
                  <circle cx={18} cy={18} r={RING_RADIUS} className="cc-confidence-ring-track" strokeWidth={3.5} fill="none" />
                  <circle
                    cx={18}
                    cy={18}
                    r={RING_RADIUS}
                    className="cc-confidence-ring-value"
                    strokeWidth={3.5}
                    fill="none"
                    stroke={ringColor}
                    strokeDasharray={RING_CIRCUMFERENCE}
                    strokeDashoffset={ringOffset}
                    strokeLinecap="round"
                  />
                </svg>
                <span className="cc-confidence-ring-label">{confidencePct}%</span>
              </span>
            </dd>
          </div>
        )}
      </dl>
    </header>
  )
}
