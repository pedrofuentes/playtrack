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
  name: 'Returned Source Name',
  width: 4096,
  height: 1024,
  fps: 30,
  nbFrames: 930,
  duration: 31,
}

let controller: WorkspaceController | null = null

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve
    reject = onReject
  })
  return { promise, resolve, reject }
}

function savedPlayerFixture() {
  const player: LibraryTrack = {
    jobId: 'saved-track',
    name: 'White 19',
    anchorFrameIdx: 42,
    box: [10, 20, 30, 60],
    startFrameIdx: 30,
    endFrameExclusive: 90,
    frameCount: 60,
    lostCount: 0,
    createdAt: '2026-07-17T00:00:00Z',
  }
  const saved: LibraryVideo = {
    videoId: 'saved-video',
    name: 'saved.mp4',
    sourceKind: 'path',
    path: '/saved.mp4',
    metadata: { ...video, videoId: 'saved-video', name: 'saved.mp4' },
    size: 100,
    openedAt: '2026-07-17T00:00:00Z',
    sourceExists: true,
    tracks: [player],
    exports: [],
  }
  const track: TrackJobUpdate = {
    jobId: player.jobId,
    state: 'completed',
    progress: 1,
    message: 'Tracking complete',
    track: [{ frameIdx: 42, box: player.box, center: [20, 40], lost: false }],
  }
  return { player, saved, track }
}

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
    expect(controller?.range).toEqual({ startFrameIdx: 0, endFrameExclusive: 930 })
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
      { startFrameIdx: 0, endFrameExclusive: 930 },
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

  it('sets half-open in/out points from the current frame and resets to the full video', async () => {
    const root = await mountController()

    act(() => controller?.setCurrentFrame(250))
    act(() => controller?.setRangeIn())
    expect(controller?.range).toEqual({ startFrameIdx: 250, endFrameExclusive: 930 })

    act(() => controller?.setCurrentFrame(700))
    act(() => controller?.setRangeOut())
    expect(controller?.range).toEqual({ startFrameIdx: 250, endFrameExclusive: 701 })

    act(() => controller?.resetRange())
    expect(controller?.range).toEqual({ startFrameIdx: 0, endFrameExclusive: 930 })
    await act(async () => root.unmount())
  })

  it('aborts and clears stale selection state whenever a boundary changes', async () => {
    const pendingSignals: AbortSignal[] = []
    apiMocks.selectByClick.mockImplementation((_videoId, _frame, _x, _y, signal) => {
      pendingSignals.push(signal)
      return new Promise(() => {})
    })
    const root = await mountController()

    act(() => controller?.selectAt({ x: 10, y: 20 }, 20))
    expect(controller?.selectionLoading).toBe(true)
    act(() => controller?.setRange({ startFrameIdx: 10, endFrameExclusive: 100 }))

    expect(pendingSignals[0].aborted).toBe(true)
    expect(controller?.selection).toBeNull()
    expect(controller?.candidates).toEqual([])
    expect(controller?.selectionError).toBeNull()
    expect(controller?.selectionLoading).toBe(false)
    await act(async () => root.unmount())
  })

  it('rejects click, text, and candidate anchors outside the selected range', async () => {
    const root = await mountController()
    act(() => controller?.setRange({ startFrameIdx: 10, endFrameExclusive: 20 }))

    act(() => controller?.selectAt({ x: 10, y: 20 }, 9))
    expect(apiMocks.selectByClick).not.toHaveBeenCalled()

    act(() => controller?.setCurrentFrame(20))
    act(() => controller?.selectByDescription('white jersey'))
    expect(apiMocks.selectByText).not.toHaveBeenCalled()

    act(() => controller?.confirmCandidate({ box: [1, 2, 3, 4], score: 1 }, 20))
    expect(controller?.selection).toBeNull()

    await act(async () => {
      controller?.selectAt({ x: 10, y: 20 }, 10)
      await Promise.resolve()
    })
    expect(apiMocks.selectByClick).toHaveBeenCalledOnce()
    expect(controller?.selection).not.toBeNull()
    await act(async () => root.unmount())
  })

  it('freezes the submitted range while tracking is starting', async () => {
    let resolveStart: ((value: { jobId: string; playerName: string }) => void) | null = null
    apiMocks.startTracking.mockImplementation(() => new Promise((resolve) => {
      resolveStart = resolve
    }))
    const root = await mountController()
    await act(async () => {
      controller?.selectAt({ x: 10, y: 20 }, 20)
      await Promise.resolve()
    })

    let starting: Promise<void> | undefined
    act(() => {
      starting = controller?.startTrack()
    })
    expect(controller?.trackStarting).toBe(true)
    act(() => controller?.setRange({ startFrameIdx: 10, endFrameExclusive: 100 }))
    expect(controller?.range).toEqual({ startFrameIdx: 0, endFrameExclusive: 930 })

    await act(async () => {
      resolveStart?.({ jobId: 'track-1', playerName: 'White 19' })
      await starting
    })
    await act(async () => root.unmount())
  })

  it('submits one tracking job and blocks destructive workspace actions while starting', async () => {
    const pending = deferred<{ jobId: string; playerName: string }>()
    apiMocks.startTracking.mockReturnValue(pending.promise)
    const root = await mountController()
    await act(async () => {
      controller?.selectAt({ x: 10, y: 20 }, 20)
      await Promise.resolve()
    })
    apiMocks.registerVideo.mockClear()

    let first: Promise<void> | undefined
    let second: Promise<void> | undefined
    act(() => {
      first = controller?.startTrack()
      second = controller?.startTrack()
      controller?.resetSelection()
      controller?.setRange({ startFrameIdx: 10, endFrameExclusive: 100 })
      void controller?.openPath('/other.mp4')
    })

    expect(apiMocks.startTracking).toHaveBeenCalledOnce()
    expect(apiMocks.registerVideo).not.toHaveBeenCalled()
    expect(controller?.selection).not.toBeNull()
    expect(controller?.range).toEqual({ startFrameIdx: 0, endFrameExclusive: 930 })

    await act(async () => {
      pending.resolve({ jobId: 'track-1', playerName: 'White 19' })
      await Promise.all([first, second])
    })
    expect(controller?.trackJob?.jobId).toBe('track-1')
    await act(async () => root.unmount())
  })

  it('unlocks cleanly after tracking submission fails', async () => {
    const pending = deferred<{ jobId: string; playerName: string }>()
    apiMocks.startTracking.mockReturnValueOnce(pending.promise)
    const root = await mountController()
    await act(async () => {
      controller?.selectAt({ x: 10, y: 20 }, 20)
      await Promise.resolve()
    })

    let starting: Promise<void> | undefined
    act(() => { starting = controller?.startTrack() })
    await act(async () => {
      pending.reject(new Error('Queue unavailable'))
      await starting
    })
    expect(controller?.trackStarting).toBe(false)
    expect(controller?.videoSwitchLocked).toBe(false)
    expect(controller?.selection).not.toBeNull()
    expect(controller?.trackError).toBe('Queue unavailable')

    await act(async () => { await controller?.startTrack() })
    expect(apiMocks.startTracking).toHaveBeenCalledTimes(2)
    await act(async () => root.unmount())
  })

  it('ignores a stale saved-player completion after a newer path open commits', async () => {
    const restore = deferred<TrackJobUpdate>()
    const registration = deferred<VideoMetadata>()
    const { player, saved, track } = savedPlayerFixture()
    const root = await mountController()
    apiMocks.getTrack.mockClear()
    apiMocks.registerVideo.mockClear()
    apiMocks.getTrack.mockReturnValueOnce(restore.promise)
    apiMocks.registerVideo.mockReturnValueOnce(registration.promise)

    let playerOpen: Promise<boolean> | undefined
    let pathOpen: Promise<void> | undefined
    act(() => {
      playerOpen = controller?.openLibraryPlayer(saved, player)
      pathOpen = controller?.openPath('/new.mp4')
    })
    expect(apiMocks.getTrack).toHaveBeenCalledOnce()
    expect(apiMocks.registerVideo).toHaveBeenCalledOnce()
    expect(playerOpen).toBeDefined()
    expect(pathOpen).toBeDefined()
    expect(controller?.loading).toBe(true)

    const newerVideo = { ...video, videoId: 'new-video', name: 'new.mp4' }
    await act(async () => {
      registration.resolve(newerVideo)
      await pathOpen
    })
    expect(controller?.video?.videoId).toBe('new-video')

    await act(async () => {
      restore.resolve(track)
      await expect(playerOpen).resolves.toBe(false)
    })
    expect(controller?.video?.videoId).toBe('new-video')
    expect(controller?.trackJob).toBeNull()
    expect(controller?.loading).toBe(false)
    await act(async () => root.unmount())
  })

  it('ignores a stale path completion while a newer saved-player restore is pending', async () => {
    const registration = deferred<VideoMetadata>()
    const restore = deferred<TrackJobUpdate>()
    const { player, saved, track } = savedPlayerFixture()
    const root = await mountController()
    apiMocks.registerVideo.mockClear()
    apiMocks.getTrack.mockClear()
    apiMocks.registerVideo.mockReturnValueOnce(registration.promise)
    apiMocks.getTrack.mockReturnValueOnce(restore.promise)

    let pathOpen: Promise<void> | undefined
    let playerOpen: Promise<boolean> | undefined
    act(() => {
      pathOpen = controller?.openPath('/old.mp4')
      playerOpen = controller?.openLibraryPlayer(saved, player)
    })
    expect(apiMocks.registerVideo).toHaveBeenCalledOnce()
    expect(apiMocks.getTrack).toHaveBeenCalledOnce()
    expect(pathOpen).toBeDefined()
    expect(playerOpen).toBeDefined()
    expect(controller?.loading).toBe(true)

    await act(async () => {
      registration.resolve({ ...video, videoId: 'stale-video', name: 'old.mp4' })
      await pathOpen
    })
    expect(controller?.video?.videoId).toBe(video.videoId)
    expect(controller?.loading).toBe(true)

    await act(async () => {
      restore.resolve(track)
      await expect(playerOpen).resolves.toBe(true)
    })
    expect(controller?.video?.videoId).toBe(saved.videoId)
    expect(controller?.trackJob).toEqual(track)
    expect(controller?.loading).toBe(false)
    await act(async () => root.unmount())
  })

  it('forwards optional names and uses the source name returned by registration', async () => {
    const root = await mountController()
    const file = new File(['video'], 'filename.mp4', { type: 'video/mp4' })

    await act(async () => {
      await controller?.openPath('/videos/path-name.mp4', 'Requested Path Name')
    })
    expect(apiMocks.registerVideo).toHaveBeenLastCalledWith('/videos/path-name.mp4', 'Requested Path Name')
    expect(controller?.videoName).toBe('Returned Source Name')

    apiMocks.uploadVideo.mockResolvedValueOnce({ ...video, name: 'Returned Upload Name' })
    await act(async () => {
      await controller?.openUpload(file, 'Requested Upload Name')
    })
    expect(apiMocks.uploadVideo).toHaveBeenCalledWith(file, 'Requested Upload Name')
    expect(controller?.videoName).toBe('Returned Upload Name')
    await act(async () => root.unmount())
  })

  it('restores a saved player atomically at its anchor and preserves state on failure', async () => {
    const savedPlayer: LibraryTrack = {
      jobId: 'saved-track',
      name: 'White 19',
      anchorFrameIdx: 42,
      box: [10, 20, 30, 60],
      startFrameIdx: 30,
      endFrameExclusive: 90,
      frameCount: 930,
      lostCount: 0,
      createdAt: '2026-07-17T00:00:00Z',
    }
    const savedVideo: LibraryVideo = {
      videoId: video.videoId,
      name: 'match.mp4',
      sourceKind: 'path',
      path: '/match.mp4',
      metadata: { ...video, name: 'Stale metadata name' },
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
      await controller?.openLibraryVideo(savedVideo)
    })
    expect(controller?.videoName).toBe('match.mp4')

    await act(async () => {
      await expect(controller?.openLibraryPlayer(savedVideo, savedPlayer)).resolves.toBe(true)
    })
    expect(controller?.videoName).toBe('match.mp4')
    expect(controller?.playerName).toBe('White 19')
    expect(controller?.currentFrame).toBe(42)
    expect(controller?.trackJob).toEqual(restored)
    expect(controller?.stage).toBe('review')
    expect(controller?.range).toEqual({ startFrameIdx: 30, endFrameExclusive: 90 })

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
    expect(controller?.range).toEqual({ startFrameIdx: 30, endFrameExclusive: 90 })
    await act(async () => root.unmount())
  })
})
