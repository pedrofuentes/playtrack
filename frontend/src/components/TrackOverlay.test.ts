import { describe, expect, it } from 'vitest'

import type { TrackFrame } from '../api'
import { trackFrameAtTime } from './TrackOverlay'

const track: TrackFrame[] = [
  { frameIdx: 0, box: [10, 20, 30, 40], center: [20, 30], lost: false },
  { frameIdx: 1, box: null, center: null, lost: true },
  { frameIdx: 2, box: [20, 30, 40, 50], center: [30, 40], lost: false },
]

describe('trackFrameAtTime', () => {
  it('selects the tracked frame synchronized to video currentTime', () => {
    expect(trackFrameAtTime(track, 0.08, 30, 3)?.frameIdx).toBe(2)
  })

  it('returns null while the player is lost or the partial track is absent', () => {
    expect(trackFrameAtTime(track, 0.04, 30, 3)).toBeNull()
    expect(trackFrameAtTime(track.slice(0, 1), 0.08, 30, 3)).toBeNull()
  })
})
