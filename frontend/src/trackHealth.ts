import type { TrackFrame } from './api'

export interface TrackHealthRange {
  startFrame: number
  endFrame: number
  frameCount: number
}

export interface TrackHealthSummary {
  coveredCount: number
  lostCount: number
  coverage: number
  lostRanges: TrackHealthRange[]
}

export function summarizeTrack(
  track: readonly TrackFrame[],
  frameCount: number,
): TrackHealthSummary {
  const ordered = [...track].sort((left, right) => left.frameIdx - right.frameIdx)
  const lostFrames = ordered.filter((frame) => frame.lost || frame.box === null)
  const coveredCount = ordered.length - lostFrames.length
  const lostRanges: TrackHealthRange[] = []

  for (const frame of lostFrames) {
    const current = lostRanges.at(-1)
    if (current && frame.frameIdx === current.endFrame + 1) {
      current.endFrame = frame.frameIdx
      current.frameCount += 1
    } else {
      lostRanges.push({
        startFrame: frame.frameIdx,
        endFrame: frame.frameIdx,
        frameCount: 1,
      })
    }
  }

  return {
    coveredCount,
    lostCount: lostFrames.length,
    coverage: frameCount > 0 ? coveredCount / frameCount : 0,
    lostRanges,
  }
}
