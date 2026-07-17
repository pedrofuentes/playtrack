// @vitest-environment jsdom

import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { TrackTimeline } from './TrackTimeline'

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
})

afterEach(() => {
  document.body.innerHTML = ''
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it('shows coverage, lost frames, and current source time', async () => {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)

  await act(async () => root.render(
    <TrackTimeline
      currentFrame={20}
      frameCount={100}
      fps={25}
      jobProgress={1}
      health={{
        coveredCount: 97,
        lostCount: 3,
        coverage: 0.97,
        lostRanges: [{ startFrame: 40, endFrame: 42, frameCount: 3 }],
      }}
      onSeek={vi.fn()}
    />,
  ))

  expect(container.textContent).toContain('97% coverage')
  expect(container.textContent).toContain('3 lost')
  expect(container.textContent).toContain('Frame 20 / 100')
  expect(container.textContent).toContain('00:00.8')
  expect(container.querySelector('[aria-label="Frames 40–42 need review"]')).not.toBeNull()
  await act(async () => root.unmount())
})

it('seeks to the first frame of a lost range', async () => {
  const onSeek = vi.fn()
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)

  await act(async () => root.render(
    <TrackTimeline
      currentFrame={0}
      frameCount={100}
      fps={25}
      jobProgress={0.5}
      health={{
        coveredCount: 48,
        lostCount: 2,
        coverage: 0.48,
        lostRanges: [{ startFrame: 40, endFrame: 41, frameCount: 2 }],
      }}
      onSeek={onSeek}
    />,
  ))

  await act(async () => {
    container.querySelector<HTMLButtonElement>('[aria-label="Frames 40–41 need review"]')?.click()
  })

  expect(onSeek).toHaveBeenCalledWith(40)
  await act(async () => root.unmount())
})
