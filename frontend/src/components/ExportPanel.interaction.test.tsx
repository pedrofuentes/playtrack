// @vitest-environment jsdom

import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { ExportPanel } from './ExportPanel'

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
  apiMocks.fetchCropPlan.mockResolvedValue({ videoId: 'video-1', trackJobId: 'track-1', windows: [] })
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
