import type { CSSProperties, KeyboardEvent } from 'react'

import {
  frameRangeCount,
  type FrameRange,
  normalizeFrameRange,
} from '../frameRange'
import type { TrackHealthSummary } from '../trackHealth'

interface TrackTimelineProps {
  currentFrame: number
  frameCount: number
  fps: number
  range: FrameRange
  rangeEditable: boolean
  jobProgress: number | null
  health: TrackHealthSummary | null
  onRangeChange: (range: FrameRange) => void
  onSeek: (frameIdx: number) => void
}

export function TrackTimeline({
  currentFrame,
  frameCount,
  fps,
  range,
  rangeEditable,
  jobProgress,
  health,
  onRangeChange,
  onSeek,
}: TrackTimelineProps) {
  const safeFrameCount = Math.max(1, frameCount)
  const safeRange = normalizeFrameRange(range, safeFrameCount)
  const selectedFrameCount = frameRangeCount(safeRange)
  const startPercent = percent(safeRange.startFrameIdx, safeFrameCount)
  const endPercent = percent(safeRange.endFrameExclusive, safeFrameCount)
  const selectedPercent = percent(selectedFrameCount, safeFrameCount)
  const afterPercent = percent(safeFrameCount - safeRange.endFrameExclusive, safeFrameCount)
  const playhead = percent(clamp(currentFrame, 0, safeFrameCount), safeFrameCount)
  const progress = jobProgress === null ? 0 : clamp(jobProgress, 0, 1)
  const outFrameIdx = safeRange.endFrameExclusive - 1

  const changeStart = (startFrameIdx: number) => {
    onRangeChange(normalizeFrameRange({ ...safeRange, startFrameIdx }, safeFrameCount))
  }
  const changeOut = (inclusiveOutFrameIdx: number) => {
    onRangeChange(normalizeFrameRange({
      ...safeRange,
      endFrameExclusive: inclusiveOutFrameIdx + 1,
    }, safeFrameCount))
  }
  const handleFrameKey = (
    event: KeyboardEvent<HTMLInputElement>,
    value: number,
    change: (next: number) => void,
  ) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    change(value + (event.key === 'ArrowRight' ? 1 : -1))
  }

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
          className="timeline-included-range"
          data-included-range
          style={{ left: `${startPercent}%`, width: `${selectedPercent}%` }}
          aria-hidden="true"
        />
        <div
          className="timeline-progress"
          style={{
            left: `${startPercent}%`,
            width: `${selectedPercent * progress}%`,
          }}
          aria-hidden="true"
        />
        {health?.lostRanges.map((lostRange) => {
          const left = clamp(lostRange.startFrame / safeFrameCount, 0, 1)
          const width = Math.max(lostRange.frameCount / safeFrameCount, 0.004)
          const label = lostRange.startFrame === lostRange.endFrame
            ? `Frame ${lostRange.startFrame} needs review`
            : `Frames ${lostRange.startFrame}–${lostRange.endFrame} need review`
          const style = {
            '--range-left': `${left * 100}%`,
            '--range-width': `${Math.min(width, 1 - left) * 100}%`,
          } as CSSProperties
          return (
            <button
              key={`${lostRange.startFrame}:${lostRange.endFrame}`}
              type="button"
              className="timeline-lost-range"
              style={style}
              aria-label={label}
              title={label}
              onClick={() => onSeek(lostRange.startFrame)}
            />
          )
        })}
        <div
          className="timeline-excluded is-before"
          data-excluded="before"
          style={{ width: `${startPercent}%` }}
          aria-hidden="true"
        />
        <div
          className="timeline-excluded is-after"
          data-excluded="after"
          style={{ left: `${endPercent}%`, width: `${afterPercent}%` }}
          aria-hidden="true"
        />
        <input
          className="timeline-range-handle is-in"
          type="range"
          min={0}
          max={safeFrameCount - 1}
          step={1}
          value={safeRange.startFrameIdx}
          disabled={!rangeEditable}
          aria-label="In point"
          aria-valuetext={`${formatTime(safeRange.startFrameIdx, fps)}, frame ${safeRange.startFrameIdx}`}
          aria-describedby="timeline-range-summary"
          onInput={(event) => changeStart(Number(event.currentTarget.value))}
          onKeyDown={(event) => handleFrameKey(event, safeRange.startFrameIdx, changeStart)}
        />
        <input
          className="timeline-range-handle is-out"
          type="range"
          min={0}
          max={safeFrameCount - 1}
          step={1}
          value={outFrameIdx}
          disabled={!rangeEditable}
          aria-label="Out point"
          aria-valuetext={`${formatTime(outFrameIdx, fps)}, frame ${outFrameIdx}`}
          aria-describedby="timeline-range-summary"
          onInput={(event) => changeOut(Number(event.currentTarget.value))}
          onKeyDown={(event) => handleFrameKey(event, outFrameIdx, changeOut)}
        />
        <div
          className="timeline-playhead"
          style={{ left: `${playhead}%` }}
          aria-hidden="true"
        />
      </div>
      <div className="timeline-range-row">
        <span id="timeline-range-summary" className="timeline-range-summary">
          {formatTime(safeRange.startFrameIdx, fps)}–{formatTime(safeRange.endFrameExclusive, fps)}
          {' · '}{formatSelectedDuration(selectedFrameCount, fps)}
          {' · '}{selectedFrameCount} frame{selectedFrameCount === 1 ? '' : 's'}
        </span>
        <div className="timeline-range-actions" role="group" aria-label="Selected range">
          <button
            type="button"
            disabled={!rangeEditable}
            onClick={() => changeStart(currentFrame)}
          >Set In</button>
          <button
            type="button"
            disabled={!rangeEditable}
            onClick={() => changeOut(currentFrame)}
          >Set Out</button>
          <button
            type="button"
            disabled={!rangeEditable}
            onClick={() => onRangeChange({ startFrameIdx: 0, endFrameExclusive: safeFrameCount })}
          >Reset</button>
        </div>
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

function formatSelectedDuration(frameCount: number, fps: number): string {
  const seconds = fps > 0 ? frameCount / fps : 0
  return `${seconds.toFixed(1)} sec`
}

function percent(frameIdx: number, frameCount: number): number {
  return Number((clamp(frameIdx / frameCount, 0, 1) * 100).toFixed(6))
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum)
}
