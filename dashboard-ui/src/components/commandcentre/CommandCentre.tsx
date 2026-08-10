import { useCallback, useEffect, useRef, useState } from 'react'
import type { CcEngagement, CcEventType } from '../../lib/commandCentre/types'
import { EngagementHeader } from './EngagementHeader'
import { EngagementPulse } from './EngagementPulse'
import { AgentTimeline } from './AgentTimeline'
import { ReplayControls } from './ReplayControls'
import { EventDetailPanel } from './EventDetailPanel'
import { ConversationPanel } from './ConversationPanel'
import { LoopDetail } from './LoopDetail'
import { CostByAgent } from './CostByAgent'
import { TopEventTypesByCost } from './TopEventTypesByCost'
import { EngagementStatePanel } from './EngagementStatePanel'
import './ccStyles.css'

export interface CommandCentreProps {
  engagement: CcEngagement
}

const DEFAULT_SPEED = 1

// Container for the Engagement Command Centre - owns selection state (one of an event or a
// loop is "open" in the sidebar at a time) and the replay clock. The replay clock advances via
// requestAnimationFrame using real elapsed wall-time between frames (never a fixed per-tick
// step), so changing `speed` mid-playback feels smooth rather than jumpy.
export function CommandCentre({ engagement }: CommandCentreProps) {
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null)
  const [selectedLoopId, setSelectedLoopId] = useState<string | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [speed, setSpeed] = useState<number>(DEFAULT_SPEED)
  const [currentTime, setCurrentTime] = useState(0)

  const rafRef = useRef<number | null>(null)
  const lastFrameRef = useRef<number | null>(null)

  useEffect(() => {
    if (!isPlaying) {
      lastFrameRef.current = null
      return
    }

    const tick = (timestamp: number) => {
      if (lastFrameRef.current === null) {
        lastFrameRef.current = timestamp
      }
      const deltaSeconds = (timestamp - lastFrameRef.current) / 1000
      lastFrameRef.current = timestamp

      setCurrentTime((prev) => {
        const next = prev + deltaSeconds * speed
        if (next >= engagement.durationSeconds) {
          setIsPlaying(false)
          return engagement.durationSeconds
        }
        return next
      })
      rafRef.current = requestAnimationFrame(tick)
    }

    rafRef.current = requestAnimationFrame(tick)
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
      rafRef.current = null
      lastFrameRef.current = null
    }
  }, [isPlaying, speed, engagement.durationSeconds])

  const handleSelectEvent = useCallback((id: string) => {
    setSelectedEventId(id)
    setSelectedLoopId(null)
  }, [])

  const handleSelectLoop = useCallback((loopId: string) => {
    setSelectedLoopId(loopId)
    setSelectedEventId(null)
  }, [])

  const handleTogglePlay = useCallback(() => {
    setIsPlaying((prev) => {
      if (!prev && currentTime >= engagement.durationSeconds) {
        setCurrentTime(0)
      }
      return !prev
    })
  }, [currentTime, engagement.durationSeconds])

  const handleSeek = useCallback(
    (seconds: number) => {
      setCurrentTime(Math.min(Math.max(seconds, 0), engagement.durationSeconds))
    },
    [engagement.durationSeconds],
  )

  const handleRestart = useCallback(() => {
    setIsPlaying(false)
    setCurrentTime(0)
  }, [])

  // Optional wiring for EngagementStatePanel's counters - selects the first matching event
  // rather than building full type filtering into AgentTimeline (out of scope here).
  const handleSelectEventType = useCallback(
    (type: CcEventType) => {
      const match = engagement.events.find((e) => e.type === type)
      if (match) handleSelectEvent(match.id)
    },
    [engagement.events, handleSelectEvent],
  )

  const selectedEvent = selectedEventId ? (engagement.events.find((e) => e.id === selectedEventId) ?? null) : null
  const selectedLoop = selectedLoopId ? (engagement.loops.find((l) => l.id === selectedLoopId) ?? null) : null

  // Data-driven (not a `synthetic` check) so Cost by Agent / Top Event Types by Cost come back
  // on their own if a future real data source ever situationally carries per-event cost - see
  // lib/commandCentre/fromReal.ts's own doc comment on why real events never set `event.cost`
  // today.
  const hasEventCostData = engagement.events.some((e) => e.cost !== undefined)

  return (
    <div className="cc-root">
      {engagement.synthetic && (
        <div className="cc-synthetic-badge" role="status">
          <span className="cc-synthetic-dot" aria-hidden="true" />
          SYNTHETIC DEMO DATA — no real telemetry
        </div>
      )}

      <div className="cc-layout">
        <div className="cc-main">
          <EngagementHeader engagement={engagement} currentTime={currentTime} />
          <EngagementPulse
            engagement={engagement}
            selectedEventId={selectedEventId}
            onSelectEvent={handleSelectEvent}
            currentTime={currentTime}
          />
          <AgentTimeline
            engagement={engagement}
            selectedEventId={selectedEventId}
            onSelectEvent={handleSelectEvent}
            onSelectLoop={handleSelectLoop}
            currentTime={currentTime}
          />
          <ReplayControls
            isPlaying={isPlaying}
            onTogglePlay={handleTogglePlay}
            speed={speed}
            onSpeedChange={setSpeed}
            currentTime={currentTime}
            duration={engagement.durationSeconds}
            // Day-granular real data very often lands every event on the same calendar day -
            // durationSeconds floors at 0, and the replay clock's own guard (currentTime can
            // never exceed duration) then makes Play flip isPlaying true and instantly false
            // again on the very first frame: a real bug, not a hypothetical one - caught live on
            // this project's own single real engagement, where Play visibly "did nothing".
            // Disabling explains why instead of leaving a live-looking control silently inert.
            disabled={engagement.durationSeconds <= 0}
            onSeek={handleSeek}
            onRestart={handleRestart}
          />
          <p className="max-w-[66ch] text-xs text-muted">
            Day-granular: no per-second timing, confidence scores, or conversation text - none of
            that is recorded today. Replay is disabled when an engagement opens and closes on the
            same day.
          </p>
        </div>

        <div className="cc-sidebar">
          {selectedLoopId ? (
            <LoopDetail loop={selectedLoop} engagement={engagement} />
          ) : (
            <>
              <EventDetailPanel event={selectedEvent} engagement={engagement} />
              {/* Only mounted when there's a real exchange to show, rather than permanently
                  occupying sidebar space with an empty state - see ConversationPanel's own
                  doc comment for the empty-state branch this skips. */}
              {selectedEvent?.conversation && <ConversationPanel event={selectedEvent} engagement={engagement} />}
            </>
          )}
          {hasEventCostData && (
            <>
              <CostByAgent engagement={engagement} />
              <TopEventTypesByCost engagement={engagement} />
            </>
          )}
          <EngagementStatePanel engagement={engagement} onSelectEventType={handleSelectEventType} />
        </div>
      </div>
    </div>
  )
}
