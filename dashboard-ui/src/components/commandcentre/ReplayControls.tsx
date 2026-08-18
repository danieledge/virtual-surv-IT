import { formatElapsed } from '../../lib/commandCentre/timelineLayout'

export interface ReplayControlsProps {
  isPlaying: boolean
  onTogglePlay: () => void
  speed: number
  onSpeedChange: (s: number) => void
  currentTime: number
  duration: number
  onSeek: (seconds: number) => void
  onRestart: () => void
  // True when there's genuinely nothing to play (duration <= 0) - disables every control
  // instead of leaving Play clickable-but-inert. See CommandCentre's own doc comment.
  disabled?: boolean
}

const SPEEDS = [0.5, 1, 2, 5]

export function ReplayControls({
  isPlaying,
  onTogglePlay,
  speed,
  onSpeedChange,
  currentTime,
  duration,
  onSeek,
  onRestart,
  disabled = false,
}: ReplayControlsProps) {
  return (
    <section className="cc-replay" aria-label="Replay controls">
      <button
        type="button"
        className="cc-replay-btn cc-replay-btn-restart"
        onClick={onRestart}
        aria-label="Restart replay"
        disabled={disabled}
      >
        <span aria-hidden="true">⟲</span>
      </button>

      <button
        type="button"
        className="cc-replay-btn cc-replay-btn-play"
        onClick={onTogglePlay}
        aria-label={isPlaying ? 'Pause replay' : 'Play replay'}
        aria-pressed={isPlaying}
        disabled={disabled}
      >
        <span aria-hidden="true">{isPlaying ? '❚❚' : '▶'}</span>
      </button>

      <div className="cc-replay-speeds" role="group" aria-label="Playback speed">
        {SPEEDS.map((s) => (
          <button
            key={s}
            type="button"
            className={`cc-speed-btn${speed === s ? ' is-active' : ''}`}
            aria-pressed={speed === s}
            aria-label={`${s}× speed`}
            onClick={() => onSpeedChange(s)}
            disabled={disabled}
          >
            {s}×
          </button>
        ))}
      </div>

      <input
        type="range"
        className="cc-replay-scrubber"
        min={0}
        max={duration}
        step={1}
        value={Math.round(currentTime)}
        onChange={(e) => onSeek(Number(e.target.value))}
        aria-label="Seek replay position"
        disabled={disabled}
      />

      {disabled ? (
        <span className="cc-replay-time text-muted" title="Every event in this engagement's data lands at the same recorded time - nothing to replay.">
          Nothing to replay
        </span>
      ) : (
        <span className="cc-replay-time">
          {formatElapsed(currentTime)} <span className="cc-metric-sub">/ {formatElapsed(duration)}</span>
        </span>
      )}
    </section>
  )
}
