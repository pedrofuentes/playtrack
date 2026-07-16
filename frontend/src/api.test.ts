import { afterEach, describe, expect, it, vi } from 'vitest'

import { selectByClick } from './api'

describe('selectByClick', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('posts source coordinates to the bare integer click route', async () => {
    const result = {
      box: [100, 200, 140, 260] as [number, number, number, number],
      maskPng: 'iVBORw0KGgo=',
      score: 0.875,
    }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue(result),
    })
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()

    await expect(
      selectByClick('video/one', 12, 2048, 512, controller.signal),
    ).resolves.toEqual(result)
    expect(fetchMock).toHaveBeenCalledWith('/api/select/click', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        videoId: 'video/one',
        frameIdx: 12,
        x: 2048,
        y: 512,
      }),
      signal: controller.signal,
    })
  })
})

