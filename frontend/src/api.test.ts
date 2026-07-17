import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  exportDownloadUrl,
  fetchCropPlan,
  getFeatures,
  selectByClick,
  selectByText,
  startExport,
  startTracking,
  trackJobWebSocketUrl,
  uploadVideo,
} from './api'

describe('uploadVideo', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('posts the selected file as multipart form data without overriding its content type', async () => {
    const result = {
      videoId: 'uploaded-video',
      width: 1920,
      height: 1080,
      fps: 30,
      nbFrames: 90,
      duration: 3,
    }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue(result),
    })
    vi.stubGlobal('fetch', fetchMock)
    const file = new File(['video bytes'], 'match.mp4', { type: 'video/mp4' })

    await expect(uploadVideo(file)).resolves.toEqual(result)

    expect(fetchMock).toHaveBeenCalledOnce()
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/videos')
    expect(options.method).toBe('POST')
    expect(options.headers).toBeUndefined()
    expect(options.body).toBeInstanceOf(FormData)
    expect((options.body as FormData).get('file')).toBe(file)
  })
})

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

describe('LocateAnything API', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('reads the feature flag and posts a text prompt at the displayed frame', async () => {
    const featureResult = {
      textSelection: { enabled: true, reason: '' },
    }
    const selectionResult = {
      candidates: [{ box: [10, 20, 40, 80], score: 1 }],
    }
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue(featureResult),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue(selectionResult),
      })
    vi.stubGlobal('fetch', fetchMock)

    await expect(getFeatures()).resolves.toEqual(featureResult)
    await expect(selectByText('video-1', 17, 'white jersey')).resolves.toEqual(
      selectionResult.candidates,
    )
    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/features')
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/select/text', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        videoId: 'video-1',
        frameIdx: 17,
        prompt: 'white jersey',
      }),
      signal: undefined,
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

describe('export API', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const settings = {
    outWidth: 1280,
    outHeight: 720,
    zoom: 1.5,
    smoothing: {
      windowSec: 0.8,
      deadZonePx: 30,
      maxVelPxPerFrame: 28,
    },
  }

  it('fetches a crop preview with the complete smoothing query', async () => {
    const result = {
      videoId: 'video-1',
      trackJobId: 'track-1',
      windows: [{ frameIdx: 0, x: 0, y: 0, w: 1280, h: 720 }],
    }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue(result),
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchCropPlan('video-1', 'track-1', settings)).resolves.toEqual(
      result,
    )
    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/export/plan?videoId=video-1&trackJobId=track-1&outWidth=1280&outHeight=720&zoom=1.5&windowSec=0.8&deadZonePx=30&maxVelPxPerFrame=28',
    )
  })

  it('starts an export and exposes its download URL', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ jobId: 'export/1' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(startExport('video-1', 'track-1', settings)).resolves.toEqual({
      jobId: 'export/1',
    })
    expect(fetchMock).toHaveBeenCalledWith('/api/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        videoId: 'video-1',
        trackJobId: 'track-1',
        ...settings,
      }),
    })
    expect(exportDownloadUrl('export/1')).toBe('/api/exports/export%2F1.mp4')
  })
})
