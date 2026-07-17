// @vitest-environment jsdom

import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { ExportPanel } from './ExportPanel'
import { playbackGeometryAtTime } from './PlaybackOverlay'

const apiMocks = vi.hoisted(() => ({
  fetchCropPlan: vi.fn(),
}))

vi.mock('../api', async (importOriginal) => ({
  ...await importOriginal<typeof import('../api')>(),
  fetchCropPlan: apiMocks.fetchCropPlan,
}))

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  apiMocks.fetchCropPlan.mockResolvedValue({
    videoId: 'video-1',
    trackJobId: 'track-1',
    sourceStartFrame: 0,
    windows: [],
  })
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
    <ExportPanel videoId="video-1" trackJobId="track-1" onPlanChange={onPlanChange} />,
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
    <ExportPanel videoId="video-1" trackJobId="track-1" onPlanChange={onPlanChange} />,
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
