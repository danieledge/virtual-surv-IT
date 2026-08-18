import type { CcEngagement, CcEvent, CcMessage } from '../../lib/commandCentre/types'
import { formatClock } from '../../lib/commandCentre/timelineLayout'
import { agentColorVar } from './ccVisuals'
import { CcCollapsible } from './CcCollapsible'

export interface ConversationPanelProps {
  event: CcEvent | null
  engagement: CcEngagement
}

// Shown in the sidebar alongside EventDetailPanel only when the selected event carries a real
// recorded exchange (event.conversation) - see CommandCentre.tsx. The empty state below still
// exists for a direct/standalone usage of this component (e.g. a future "always visible" sidebar
// layout) rather than assuming it's only ever mounted when there's something to show.
export function ConversationPanel({ event, engagement }: ConversationPanelProps) {
  const conversation = event?.conversation

  if (!event || !conversation) {
    return (
      <section className="cc-panel" aria-label="Conversation">
        <h2 className="cc-panel-title">Conversation</h2>
        <p className="cc-empty-state">
          Select a handoff or escalation event with a recorded exchange to see the request and response here.
        </p>
      </section>
    )
  }

  const requestAgent = engagement.agents.find((a) => a.id === conversation.request.agentId)
  const responseAgent = engagement.agents.find((a) => a.id === conversation.response.agentId)

  return (
    <CcCollapsible
      ariaLabel="Conversation"
      title="Conversation"
      peek={
        <>
          {requestAgent?.name ?? conversation.request.agentId} <span aria-hidden="true">→</span>{' '}
          {responseAgent?.name ?? conversation.response.agentId}
        </>
      }
    >
      <div className="cc-conversation-stack">
        <ConversationMessage
          role="Request"
          agentName={requestAgent?.name ?? conversation.request.agentId}
          colorIndex={requestAgent?.colorIndex ?? 0}
          time={formatClock(engagement.startClock, event.startedAt)}
          message={conversation.request}
        />
        <span className="cc-conversation-arrow" aria-hidden="true">
          ↓
        </span>
        <ConversationMessage
          role="Response"
          agentName={responseAgent?.name ?? conversation.response.agentId}
          colorIndex={responseAgent?.colorIndex ?? 0}
          time={formatClock(engagement.startClock, event.completedAt)}
          message={conversation.response}
        />
      </div>

      {conversation.result && (
        <>
          <hr className="cc-conversation-rule" />
          <p className="cc-conversation-result">
            <span className="cc-conversation-result-label">Result</span> {conversation.result}
          </p>
        </>
      )}
    </CcCollapsible>
  )
}

interface ConversationMessageProps {
  role: 'Request' | 'Response'
  agentName: string
  colorIndex: number
  time: string
  message: CcMessage
}

function ConversationMessage({ role, agentName, colorIndex, time, message }: ConversationMessageProps) {
  return (
    <div className="cc-conversation-card">
      <div className="cc-conversation-card-head">
        <span
          className="cc-conversation-dot"
          style={{ background: agentColorVar(colorIndex) }}
          aria-hidden="true"
        />
        <span className="cc-conversation-agent">{agentName}</span>
        <span className="cc-conversation-role">{role}</span>
        <span className="cc-conversation-time">{time}</span>
      </div>
      <p className="cc-conversation-text">{message.text}</p>
      <div className="cc-conversation-footer">
        {message.tokens.toLocaleString('en-US')} tokens · ${message.cost.toFixed(2)}
      </div>
    </div>
  )
}
