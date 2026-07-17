import { describe, expect, it } from 'vitest'

import {
  containsFrame,
  frameRangeCount,
  normalizeFrameRange,
} from './frameRange'

describe('frame ranges', () => {
  it('normalizes boundaries to a non-empty half-open video range', () => {
    expect(normalizeFrameRange({ startFrameIdx: -20, endFrameExclusive: 1200 }, 1000))
      .toEqual({ startFrameIdx: 0, endFrameExclusive: 1000 })
    expect(normalizeFrameRange({ startFrameIdx: 700, endFrameExclusive: 250 }, 1000))
      .toEqual({ startFrameIdx: 700, endFrameExclusive: 701 })
    expect(normalizeFrameRange({ startFrameIdx: 1000, endFrameExclusive: 1000 }, 1000))
      .toEqual({ startFrameIdx: 999, endFrameExclusive: 1000 })
  })

  it('counts included frames and excludes the end boundary from anchors', () => {
    const range = { startFrameIdx: 250, endFrameExclusive: 701 }
    expect(frameRangeCount(range)).toBe(451)
    expect(containsFrame(range, 250)).toBe(true)
    expect(containsFrame(range, 700)).toBe(true)
    expect(containsFrame(range, 701)).toBe(false)
  })
})
