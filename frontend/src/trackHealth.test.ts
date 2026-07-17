import { describe, expect, it } from 'vitest'

import type { TrackFrame } from './api'
import { summarizeTrack } from './trackHealth'

function frame(frameIdx: number, lost: boolean): TrackFrame {
  return {
    frameIdx,
    box: lost ? null : [frameIdx, 1, frameIdx + 1, 2],
    center: lost ? null : [frameIdx + 0.5, 1.5],
    lost,
  }
}

describe('summarizeTrack', () => {
  it('summarizes coverage and contiguous lost ranges', () => {
    expect(summarizeTrack([
      frame(0, false),
      frame(1, true),
      frame(2, true),
      frame(3, false),
    ], 4)).toEqual({
      coveredCount: 2,
      lostCount: 2,
      coverage: 0.5,
      lostRanges: [{ startFrame: 1, endFrame: 2, frameCount: 2 }],
    })
  })

  it('sorts frames, treats null boxes as lost, and separates gaps', () => {
    const track = [frame(5, true), frame(1, false), frame(3, true)]
    track[2] = { ...track[2], lost: false, box: null }

    expect(summarizeTrack(track, 8)).toEqual({
      coveredCount: 1,
      lostCount: 2,
      coverage: 0.125,
      lostRanges: [
        { startFrame: 3, endFrame: 3, frameCount: 1 },
        { startFrame: 5, endFrame: 5, frameCount: 1 },
      ],
    })
  })

  it('does not classify frames missing from a partial track as lost', () => {
    expect(summarizeTrack([frame(10, false)], 0)).toEqual({
      coveredCount: 1,
      lostCount: 0,
      coverage: 0,
      lostRanges: [],
    })
  })
})
