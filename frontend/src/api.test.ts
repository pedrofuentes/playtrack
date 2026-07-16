import { afterEach, describe, expect, it, vi } from 'vitest'

import { selectByClick, startTracking, trackJobWebSocketUrl } from './api'

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

describe('startTracking', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('starts tracking with the anchor frame and source box', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ jobId: 'job-1' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      startTracking('video-1', 12, [100, 200, 140, 260]),
    ).resolves.toEqual({ jobId: 'job-1' })
    expect(fetchMock).toHaveBeenCalledWith('/api/track', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        videoId: 'video-1',
        frameIdx: 12,
        box: [100, 200, 140, 260],
      }),
    })
  })
})

describe('trackJobWebSocketUrl', () => {
  it('uses the page host and secure websocket protocol when appropriate', () => {
    expect(
      trackJobWebSocketUrl('job/one', {
        protocol: 'https:',
        host: 'findme.local',
      }),
    ).toBe('wss://findme.local/ws/jobs/job%2Fone')
  })
})
