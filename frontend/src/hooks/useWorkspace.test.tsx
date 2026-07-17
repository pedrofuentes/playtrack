// @vitest-environment jsdom

import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { TrackJobUpdate, VideoMetadata } from '../api'
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
  apiMocks.startTracking.mockResolvedValue({ jobId: 'track-1' })
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

    await act(async () => {
      await controller?.startTrack()
    })
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
})
