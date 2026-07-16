import { describe, expect, it } from 'vitest'

import {
  canvasRectFromSourceBox,
  displayedFrameIndex,
  sourcePointFromCanvas,
} from './geometry'

describe('sourcePointFromCanvas', () => {
  it('maps a panoramic source through vertical letterboxing', () => {
    expect(
      sourcePointFromCanvas(
        { x: 500, y: 250 },
        { width: 1000, height: 500 },
        { width: 4096, height: 1024 },
      ),
    ).toEqual({ x: 2048, y: 512 })
  })

  it('maps a portrait source through horizontal letterboxing', () => {
    expect(
      sourcePointFromCanvas(
        { x: 500, y: 250 },
        { width: 1000, height: 500 },
        { width: 100, height: 200 },
      ),
    ).toEqual({ x: 50, y: 100 })
  })

  it('ignores clicks in vertical padding', () => {
    expect(
      sourcePointFromCanvas(
        { x: 500, y: 20 },
        { width: 1000, height: 500 },
        { width: 4096, height: 1024 },
      ),
    ).toBeNull()
  })

  it('ignores clicks in horizontal padding', () => {
    expect(
      sourcePointFromCanvas(
        { x: 100, y: 250 },
        { width: 1000, height: 500 },
        { width: 100, height: 200 },
      ),
    ).toBeNull()
  })

  it('clamps the bottom-right edge to valid source pixels', () => {
    expect(
      sourcePointFromCanvas(
        { x: 1000, y: 500 },
        { width: 1000, height: 500 },
        { width: 1000, height: 500 },
      ),
    ).toEqual({ x: 999, y: 499 })
  })

  it('returns null for dimensions that are not ready', () => {
    expect(
      sourcePointFromCanvas(
        { x: 0, y: 0 },
        { width: 0, height: 0 },
        { width: 0, height: 0 },
      ),
    ).toBeNull()
  })
})

describe('displayedFrameIndex', () => {
  it('uses the frame currently displayed and clamps to video bounds', () => {
    expect(displayedFrameIndex(0.05, 30, 930)).toBe(1)
    expect(displayedFrameIndex(-1, 30, 930)).toBe(0)
    expect(displayedFrameIndex(31, 30, 930)).toBe(929)
  })
})

describe('canvasRectFromSourceBox', () => {
  it('projects an exclusive source box through panorama letterboxing', () => {
    expect(
      canvasRectFromSourceBox(
        [1024, 256, 2048, 768],
        { width: 1000, height: 500 },
        { width: 4096, height: 1024 },
      ),
    ).toEqual({ left: 250, top: 187.5, width: 250, height: 125 })
  })
})
