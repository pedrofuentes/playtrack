// @vitest-environment jsdom

import { act, createRef } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { type ExportPanelHandle, ExportPanel } from './ExportPanel'
import { playbackGeometryAtTime } from './PlaybackOverlay'

const apiMocks = vi.hoisted(() => ({
  fetchCropPlan: vi.fn(),
  startExport: vi.fn(),
  watchTrackJob: vi.fn(),
}))

vi.mock('../api', async (importOriginal) => ({
  ...await importOriginal<typeof import('../api')>(),
  ...apiMocks,
}))

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve
    reject = onReject
  })
  return { promise, resolve, reject }
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  apiMocks.fetchCropPlan.mockResolvedValue({
    videoId: 'video-1',
    trackJobId: 'track-1',
    sourceStartFrame: 0,
    windows: [],
  })
  apiMocks.startExport.mockResolvedValue({ jobId: 'export-1' })
  apiMocks.watchTrackJob.mockReturnValue({ close: vi.fn() } as unknown as WebSocket)
})

afterEach(() => {
  document.body.innerHTML = ''
  vi.useRealTimers()
  vi.clearAllMocks()
  vi.unstubAllGlobals()
})

it('debounces crop preview requests by 150 ms', async () => {
  const onPlanChange = vi.fn()
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  await act(async () => root.render(
    <ExportPanel
      videoId="video-1"
      trackJobId="track-1"
      exportStarting={false}
      onExportStart={vi.fn().mockReturnValue(1)}
      onExportFinish={vi.fn()}
      onPlanChange={onPlanChange}
    />,
  ))

  expect(apiMocks.fetchCropPlan).not.toHaveBeenCalled()
  await act(async () => vi.advanceTimersByTime(149))
  expect(apiMocks.fetchCropPlan).not.toHaveBeenCalled()
  await act(async () => {
    vi.advanceTimersByTime(1)
    await Promise.resolve()
  })
  expect(apiMocks.fetchCropPlan).toHaveBeenCalledOnce()
  await act(async () => root.unmount())
})

it('maps output-local preview windows onto absolute source playback frames', async () => {
  const localWindows = Array.from({ length: 16 }, (_, frameIdx) => ({
    frameIdx,
    x: frameIdx,
    y: 0,
    w: 100,
    h: 60,
  }))
  apiMocks.fetchCropPlan.mockResolvedValue({
    videoId: 'video-1',
    trackJobId: 'track-1',
    sourceStartFrame: 8,
    windows: localWindows,
  })
  const onPlanChange = vi.fn()
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  await act(async () => root.render(
    <ExportPanel
      videoId="video-1"
      trackJobId="track-1"
      exportStarting={false}
      onExportStart={vi.fn().mockReturnValue(1)}
      onExportFinish={vi.fn()}
      onPlanChange={onPlanChange}
    />,
  ))

  await act(async () => {
    vi.advanceTimersByTime(150)
    await Promise.resolve()
  })

  const previewWindows = onPlanChange.mock.calls.at(-1)?.[0]
  expect(previewWindows.map((window: { frameIdx: number }) => window.frameIdx)).toEqual(
    Array.from({ length: 16 }, (_, index) => index + 8),
  )
  expect(playbackGeometryAtTime([], previewWindows, 1, 8, 32).cropWindow).toEqual({
    ...localWindows[0],
    frameIdx: 8,
  })
  expect(playbackGeometryAtTime([], previewWindows, 23 / 8, 8, 32).cropWindow).toEqual({
    ...localWindows[15],
    frameIdx: 23,
  })
  await act(async () => root.unmount())
})

async function renderReadyExport(overrides: Record<string, unknown> = {}) {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  const panelRef = createRef<ExportPanelHandle>()
  const props = {
    videoId: 'video-1',
    trackJobId: 'track-1',
    exportStarting: false,
    onExportStart: vi.fn().mockReturnValue(1),
    onExportFinish: vi.fn(),
    onPlanChange: vi.fn(),
    onJobChange: vi.fn(),
    onLibraryChange: vi.fn(),
    ...overrides,
  }
  await act(async () => root.render(<ExportPanel ref={panelRef} {...props} />))
  await act(async () => {
    vi.advanceTimersByTime(150)
    await Promise.resolve()
    await Promise.resolve()
  })
  return { container, panelRef, props, root }
}

it('submits one export when triggered twice before React rerenders', async () => {
  const pending = deferred<{ jobId: string }>()
  apiMocks.startExport.mockReturnValue(pending.promise)
  const { panelRef, props, root } = await renderReadyExport()

  act(() => {
    panelRef.current?.triggerExport()
    panelRef.current?.triggerExport()
  })

  expect(props.onExportStart).toHaveBeenCalledOnce()
  expect(apiMocks.startExport).toHaveBeenCalledOnce()
  await act(async () => root.unmount())
})

it('drops a deferred export response after unmount and releases only its token', async () => {
  const pending = deferred<{ jobId: string }>()
  apiMocks.startExport.mockReturnValue(pending.promise)
  const { panelRef, props, root } = await renderReadyExport()
  act(() => panelRef.current?.triggerExport())
  expect(apiMocks.startExport).toHaveBeenCalledOnce()
  props.onJobChange.mockClear()

  await act(async () => root.unmount())
  expect(props.onExportFinish).toHaveBeenCalledOnce()
  expect(props.onExportFinish).toHaveBeenCalledWith(1)

  await act(async () => {
    pending.resolve({ jobId: 'stale-export' })
    await pending.promise
    await Promise.resolve()
  })
  expect(props.onJobChange).not.toHaveBeenCalled()
  expect(apiMocks.watchTrackJob).not.toHaveBeenCalled()
  expect(props.onLibraryChange).not.toHaveBeenCalled()
  expect(props.onExportFinish).toHaveBeenCalledOnce()
})

it('releases a failed export start and allows a retry with a new token', async () => {
  apiMocks.startExport
    .mockRejectedValueOnce(new Error('Queue unavailable'))
    .mockResolvedValueOnce({ jobId: 'export-2' })
  const onExportStart = vi.fn()
    .mockReturnValueOnce(1)
    .mockReturnValueOnce(2)
  const { container, panelRef, props, root } = await renderReadyExport({ onExportStart })

  await act(async () => {
    panelRef.current?.triggerExport()
    await Promise.resolve()
    await Promise.resolve()
  })
  expect(props.onExportFinish).toHaveBeenCalledWith(1)
  expect(container.textContent).toContain('Queue unavailable')

  await act(async () => {
    panelRef.current?.triggerExport()
    await Promise.resolve()
    await Promise.resolve()
  })
  expect(apiMocks.startExport).toHaveBeenCalledTimes(2)
  expect(onExportStart).toHaveBeenCalledTimes(2)
  expect(props.onExportFinish).toHaveBeenCalledWith(2)
  await act(async () => root.unmount())
})
