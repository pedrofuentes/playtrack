import { describe, expect, it } from 'vitest'

import type { CropWindow } from '../api'
import { cropWindowAtTime } from './CropOverlay'

const windows: CropWindow[] = [
  { frameIdx: 0, x: 0, y: 10, w: 100, h: 50 },
  { frameIdx: 1, x: 10, y: 10, w: 100, h: 50 },
  { frameIdx: 2, x: 20, y: 10, w: 100, h: 50 },
]

describe('cropWindowAtTime', () => {
  it('selects the preview window synchronized to currentTime', () => {
    expect(cropWindowAtTime(windows, 0.08, 30, 3)).toEqual(windows[2])
  })

  it('returns null before a partial preview contains that frame', () => {
    expect(cropWindowAtTime(windows.slice(0, 1), 0.08, 30, 3)).toBeNull()
  })
})
