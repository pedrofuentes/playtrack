import { describe, expect, it } from 'vitest'

import type { LocateCandidate } from '../api'
import {
  candidateAtSourcePoint,
  clampPan,
  pointerMovedPastThreshold,
  zoomAtPoint,
} from './VideoStage'

const candidates: LocateCandidate[] = [
  { box: [10, 20, 40, 80], score: 0.9 },
  { box: [100, 120, 140, 180], score: 0.8 },
]

describe('candidateAtSourcePoint', () => {
  it('returns the candidate whose rendered source box was clicked', () => {
    expect(candidateAtSourcePoint(candidates, { x: 25, y: 50 })).toEqual(
      candidates[0],
    )
    expect(candidateAtSourcePoint(candidates, { x: 120, y: 150 })).toEqual(
      candidates[1],
    )
  })

  it('returns null outside all candidate boxes', () => {
    expect(candidateAtSourcePoint(candidates, { x: 60, y: 100 })).toBeNull()
  })
})

describe('view transforms', () => {
  it('keeps the source point under the cursor fixed while zooming', () => {
    const before = { zoom: 1, x: 0, y: 0 }
    const cursor = { x: 120, y: 60 }

    const after = zoomAtPoint(
      before,
      2,
      cursor,
      { width: 400, height: 200 },
    )

    expect(after).toEqual({ zoom: 2, x: -120, y: -60 })
    expect((cursor.x - after.x) / after.zoom).toBe(
      (cursor.x - before.x) / before.zoom,
    )
    expect((cursor.y - after.y) / after.zoom).toBe(
      (cursor.y - before.y) / before.zoom,
    )
  })

  it('clamps zoom and pan so the transformed stage always covers the viewport', () => {
    expect(clampPan({ x: 40, y: -500 }, 2, { width: 400, height: 200 })).toEqual({
      x: 0,
      y: -200,
    })
    expect(
      zoomAtPoint(
        { zoom: 4, x: -300, y: -100 },
        20,
        { x: 200, y: 100 },
        { width: 400, height: 200 },
      ).zoom,
    ).toBe(8)
  })

  it('only treats pointer movement greater than four pixels as a drag', () => {
    expect(pointerMovedPastThreshold({ x: 0, y: 0 }, { x: 4, y: 0 })).toBe(false)
    expect(pointerMovedPastThreshold({ x: 0, y: 0 }, { x: 3, y: 4 })).toBe(true)
  })
})
