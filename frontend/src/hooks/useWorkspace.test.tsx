// @vitest-environment jsdom

import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { LibraryTrack, LibraryVideo, TrackJobUpdate, VideoMetadata } from '../api'
import { type WorkspaceController, useWorkspace } from './useWorkspace'

const apiMocks = vi.hoisted(() => ({
  clearFrameCaches: vi.fn(),
  getFeatures: vi.fn(),
  getLibrary: vi.fn(),
  getTrack: vi.fn(),
  registerVideo: vi.fn(),
  selectByClick: vi.fn(),
  selectByText: vi.fn(),
  startTracking: vi.fn(),
  uploadVideo: vi.fn(),
  watchTrackJob: vi.fn(),
}))

vi.mock('../api', async (importOriginal) => ({
  ...await importOriginal<typeof import('../api')>(),
  ...apiMocks,
}))

const video: VideoMetadata = {
  videoId: 'video-1',
  width: 4096,
  height: 1024,
  fps: 30,
  nbFrames: 930,
  duration: 31,
}

let controller: WorkspaceController | null = null

function Harness() {
  controller = useWorkspace()
  return null
}

async function mountController() {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  await act(async () => {
    root.render(<Harness />)
    await Promise.resolve()
    await Promise.resolve()
  })
  return root
}

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  controller = null
  apiMocks.getFeatures.mockResolvedValue({ textSelection: { enabled: false, reason: '' } })
  apiMocks.getLibrary.mockResolvedValue({ videos: [], cacheBytes: 0 })
  apiMocks.registerVideo.mockResolvedValue(video)
  apiMocks.uploadVideo.mockResolvedValue(video)
  apiMocks.selectByClick.mockResolvedValue({ box: [1, 2, 3, 4], maskPng: '', score: 0.9 })
  apiMocks.selectByText.mockResolvedValue([])
  apiMocks.startTracking.mockResolvedValue({ jobId: 'track-1', playerName: 'White 19' })
  apiMocks.clearFrameCaches.mockResolvedValue({ bytesFreed: 0 })
  apiMocks.watchTrackJob.mockReturnValue({ close: vi.fn() } as unknown as WebSocket)
})

afterEach(() => {
  document.body.innerHTML = ''
  vi.clearAllMocks()
  vi.unstubAllGlobals()
})

describe('useWorkspace', () => {
  it('advances selection through tracking, review, framing, and export locking', async () => {
    let onTrackUpdate: ((update: TrackJobUpdate) => void) | null = null
    apiMocks.watchTrackJob.mockImplementation((_id, onUpdate) => {
      onTrackUpdate = onUpdate
      return { close: vi.fn() } as unknown as WebSocket
    })
    const root = await mountController()

    expect(controller?.video).toEqual(video)
    await act(async () => {
      controller?.selectAt({ x: 100, y: 200 }, 20)
      await Promise.resolve()
    })
    expect(controller?.selection?.score).toBe(0.9)
    expect(controller?.stage).toBe('select')

    act(() => controller?.setPlayerName(' White 19 '))
    await act(async () => {
      await controller?.startTrack()
    })
    expect(apiMocks.startTracking).toHaveBeenCalledWith(
      'video-1', 20, [1, 2, 3, 4], ' White 19 ',
    )
    expect(controller?.playerName).toBe('White 19')
    expect(controller?.videoSwitchLocked).toBe(true)
    expect(controller?.trackStartedAt).not.toBeNull()

    act(() => onTrackUpdate?.({
      jobId: 'track-1',
      state: 'completed',
      progress: 1,
      message: 'done',
      track: [],
    }))
    expect(controller?.stage).toBe('review')
    act(() => controller?.beginFraming())
    expect(controller?.stage).toBe('export')
    act(() => controller?.setExportJob({
      jobId: 'export-1',
      state: 'running',
      progress: 0.2,
      message: 'exporting',
      track: [],
    }))
    expect(controller?.videoSwitchLocked).toBe(true)
    await act(async () => root.unmount())
  })

  it('aborts a stale click selection and resets downstream state when opening a video', async () => {
    const pending: Array<{ signal: AbortSignal; resolve: (score: number) => void }> = []
    apiMocks.selectByClick.mockImplementation((_videoId, _frame, _x, _y, signal) => (
      new Promise((resolve) => pending.push({
        signal,
        resolve: (score) => resolve({ box: [1, 2, 3, 4], maskPng: '', score }),
      }))
    ))
    const root = await mountController()

    act(() => controller?.selectAt({ x: 10, y: 20 }, 1))
    act(() => controller?.selectAt({ x: 30, y: 40 }, 2))
    expect(pending[0].signal.aborted).toBe(true)
    await act(async () => pending[1].resolve(0.8))
    expect(controller?.selection?.score).toBe(0.8)

    await act(async () => {
      await controller?.openUpload(new File(['video'], 'new.mp4', { type: 'video/mp4' }))
    })
    expect(controller?.selection).toBeNull()
    expect(controller?.trackJob).toBeNull()
    expect(controller?.framing).toBe(false)
    await act(async () => root.unmount())
  })

  it('restores a saved player atomically at its anchor and preserves state on failure', async () => {
    const savedPlayer: LibraryTrack = {
      jobId: 'saved-track',
      name: 'White 19',
      anchorFrameIdx: 42,
      box: [10, 20, 30, 60],
      frameCount: 930,
      lostCount: 0,
      createdAt: '2026-07-17T00:00:00Z',
    }
    const savedVideo: LibraryVideo = {
      videoId: video.videoId,
      name: 'match.mp4',
      sourceKind: 'path',
      path: '/match.mp4',
      metadata: video,
      size: 100,
      openedAt: '2026-07-17T00:00:00Z',
      sourceExists: true,
      tracks: [savedPlayer],
      exports: [],
    }
    const restored: TrackJobUpdate = {
      jobId: 'saved-track',
      state: 'completed',
      progress: 1,
      message: 'Tracking complete',
      track: [{ frameIdx: 42, box: [10, 20, 30, 60], center: [20, 40], lost: false }],
    }
    apiMocks.getTrack.mockResolvedValue(restored)
    const root = await mountController()

    await act(async () => {
      await expect(controller?.openLibraryPlayer(savedVideo, savedPlayer)).resolves.toBe(true)
    })
    expect(controller?.videoName).toBe('match.mp4')
    expect(controller?.playerName).toBe('White 19')
    expect(controller?.currentFrame).toBe(42)
    expect(controller?.trackJob).toEqual(restored)
    expect(controller?.stage).toBe('review')

    apiMocks.getTrack.mockRejectedValueOnce(new Error('Track missing'))
    await act(async () => {
      await expect(controller?.openLibraryPlayer(
        { ...savedVideo, name: 'other.mp4' },
        { ...savedPlayer, jobId: 'missing' },
      )).rejects.toThrow('Track missing')
    })
    expect(controller?.videoName).toBe('match.mp4')
    expect(controller?.playerName).toBe('White 19')
    expect(controller?.trackJob).toEqual(restored)
    await act(async () => root.unmount())
  })
})
