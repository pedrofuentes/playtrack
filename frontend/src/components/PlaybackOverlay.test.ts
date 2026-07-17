import { describe, expect, it } from 'vitest'

import type { CropWindow, TrackFrame } from '../api'
import { playbackGeometryAtTime } from './PlaybackOverlay'

const track: TrackFrame[] = [
  { frameIdx: 0, box: [10, 20, 30, 40], center: [20, 30], lost: false },
  { frameIdx: 1, box: [20, 30, 40, 50], center: [30, 40], lost: false },
  { frameIdx: 2, box: null, center: null, lost: true },
]
const windows: CropWindow[] = [
  { frameIdx: 0, x: 0, y: 0, w: 100, h: 60 },
  { frameIdx: 1, x: 10, y: 5, w: 110, h: 62 },
  { frameIdx: 2, x: 20, y: 10, w: 120, h: 64 },
]

describe('playbackGeometryAtTime', () => {
  it('returns synchronized restored player and crop geometry for the displayed frame', () => {
    expect(playbackGeometryAtTime(track, windows, 0.11, 10, 3)).toEqual({
      frameIdx: 1,
      playerBox: [20, 30, 40, 50],
      cropWindow: windows[1],
    })
  })

  it('keeps crop geometry while suppressing a lost player box', () => {
    expect(playbackGeometryAtTime(track, windows, 0.21, 10, 3)).toEqual({
      frameIdx: 2,
      playerBox: null,
      cropWindow: windows[2],
    })
  })
})
