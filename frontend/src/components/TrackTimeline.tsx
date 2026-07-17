import type { CSSProperties } from 'react'

import type { TrackHealthSummary } from '../trackHealth'

interface TrackTimelineProps {
  currentFrame: number
  frameCount: number
  fps: number
  jobProgress: number | null
  health: TrackHealthSummary | null
  onSeek: (frameIdx: number) => void
}

export function TrackTimeline({
  currentFrame,
  frameCount,
  fps,
  jobProgress,
  health,
  onSeek,
}: TrackTimelineProps) {
  const safeFrameCount = Math.max(1, frameCount)
  const playhead = clamp(currentFrame / safeFrameCount, 0, 1)
  const progress = jobProgress === null ? 0 : clamp(jobProgress, 0, 1)

  return (
    <section className="track-timeline" aria-label="Video timeline">
      <div className="timeline-summary">
        <span className="timeline-label">Track health</span>
        <span>{formatTime(currentFrame, fps)} · Frame {currentFrame} / {frameCount}</span>
        {health && (
          <span>{Math.round(health.coverage * 100)}% coverage · {health.lostCount} lost</span>
        )}
      </div>
      <div className="timeline-track">
        <div
          className="timeline-progress"
          style={{ width: `${progress * 100}%` }}
          aria-hidden="true"
        />
        {health?.lostRanges.map((range) => {
          const left = clamp(range.startFrame / safeFrameCount, 0, 1)
          const width = Math.max(range.frameCount / safeFrameCount, 0.004)
          const label = range.startFrame === range.endFrame
            ? `Frame ${range.startFrame} needs review`
            : `Frames ${range.startFrame}–${range.endFrame} need review`
          const style = {
            '--range-left': `${left * 100}%`,
            '--range-width': `${Math.min(width, 1 - left) * 100}%`,
          } as CSSProperties
          return (
            <button
              key={`${range.startFrame}:${range.endFrame}`}
              type="button"
              className="timeline-lost-range"
              style={style}
              aria-label={label}
              title={label}
              onClick={() => onSeek(range.startFrame)}
            />
          )
        })}
        <div
          className="timeline-playhead"
          style={{ left: `${playhead * 100}%` }}
          aria-hidden="true"
        />
      </div>
    </section>
  )
}

function formatTime(frameIdx: number, fps: number): string {
  const totalSeconds = fps > 0 ? Math.max(0, frameIdx) / fps : 0
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds - minutes * 60
  return `${String(minutes).padStart(2, '0')}:${seconds.toFixed(1).padStart(4, '0')}`
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum)
}
