// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { FrameRange } from '../frameRange'
import { TrackTimeline } from './TrackTimeline'

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
})

afterEach(() => {
  document.body.innerHTML = ''
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

const health = {
  coveredCount: 97,
  lostCount: 3,
  coverage: 0.97,
  lostRanges: [{ startFrame: 40, endFrame: 42, frameCount: 3 }],
}

async function renderTimeline({
  currentFrame = 20,
  frameCount = 100,
  fps = 25,
  range = { startFrameIdx: 0, endFrameExclusive: frameCount },
  rangeEditable = true,
  onRangeChange = vi.fn(),
  onSeek = vi.fn(),
}: {
  currentFrame?: number
  frameCount?: number
  fps?: number
  range?: FrameRange
  rangeEditable?: boolean
  onRangeChange?: (range: FrameRange) => void
  onSeek?: (frameIdx: number) => void
} = {}) {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  await render(root, {
    currentFrame,
    frameCount,
    fps,
    range,
    rangeEditable,
    onRangeChange,
    onSeek,
  })
  return { container, root, onRangeChange, onSeek }
}

async function render(root: Root, props: {
  currentFrame: number
  frameCount: number
  fps: number
  range: FrameRange
  rangeEditable: boolean
  onRangeChange: (range: FrameRange) => void
  onSeek: (frameIdx: number) => void
}) {
  await act(async () => root.render(
    <TrackTimeline
      {...props}
      jobProgress={1}
      health={health}
    />,
  ))
}

function button(container: HTMLElement, name: string) {
  return [...container.querySelectorAll('button')]
    .find((item) => item.textContent?.trim() === name)!
}

describe('TrackTimeline', () => {
  it('shows coverage, lost frames, current source time, and the absolute selected range', async () => {
    const { container, root } = await renderTimeline({
      currentFrame: 250,
      frameCount: 1000,
      fps: 25,
      range: { startFrameIdx: 250, endFrameExclusive: 701 },
    })

    expect(container.textContent).toContain('97% coverage')
    expect(container.textContent).toContain('3 lost')
    expect(container.textContent).toContain('Frame 250 / 1000')
    expect(container.textContent).toContain('00:10.0')
    expect(container.textContent).toContain('00:28.0')
    expect(container.textContent).toContain('18.0 sec')
    expect(container.textContent).toContain('451 frames')
    expect(container.querySelector('[aria-label="Frames 40–42 need review"]')).not.toBeNull()
    await act(async () => root.unmount())
  })

  it('labels Out with the final included frame while duration uses the frame count', async () => {
    const { container, root } = await renderTimeline({
      currentFrame: 2,
      frameCount: 10,
      fps: 2,
      range: { startFrameIdx: 2, endFrameExclusive: 4 },
    })

    expect(container.textContent).toContain('00:01.0–00:01.5 · 1.0 sec · 2 frames')
    await act(async () => root.unmount())
  })

  it('seeks to the first frame of a lost range', async () => {
    const onSeek = vi.fn()
    const { container, root } = await renderTimeline({ onSeek })

    await act(async () => {
      container.querySelector<HTMLButtonElement>('[aria-label="Frames 40–42 need review"]')?.click()
    })

    expect(onSeek).toHaveBeenCalledWith(40)
    await act(async () => root.unmount())
  })

  it('sets inclusive current-frame in/out points and resets the full range', async () => {
    const onRangeChange = vi.fn()
    const { container, root, onSeek } = await renderTimeline({
      currentFrame: 250,
      frameCount: 1000,
      range: { startFrameIdx: 0, endFrameExclusive: 1000 },
      onRangeChange,
    })

    await act(async () => button(container, 'Set In').click())
    expect(onRangeChange).toHaveBeenLastCalledWith({
      startFrameIdx: 250,
      endFrameExclusive: 1000,
    })

    await render(root, {
      currentFrame: 700,
      frameCount: 1000,
      fps: 25,
      range: { startFrameIdx: 250, endFrameExclusive: 1000 },
      rangeEditable: true,
      onRangeChange,
      onSeek,
    })
    await act(async () => button(container, 'Set Out').click())
    expect(onRangeChange).toHaveBeenLastCalledWith({
      startFrameIdx: 250,
      endFrameExclusive: 701,
    })

    await render(root, {
      currentFrame: 700,
      frameCount: 1000,
      fps: 25,
      range: { startFrameIdx: 250, endFrameExclusive: 701 },
      rangeEditable: true,
      onRangeChange,
      onSeek,
    })
    await act(async () => button(container, 'Reset').click())
    expect(onRangeChange).toHaveBeenLastCalledWith({
      startFrameIdx: 0,
      endFrameExclusive: 1000,
    })
    await act(async () => root.unmount())
  })

  it('moves pointer handles and keyboard-focused handles in exact frames', async () => {
    const onRangeChange = vi.fn()
    const { container, root } = await renderTimeline({
      currentFrame: 400,
      frameCount: 1000,
      range: { startFrameIdx: 250, endFrameExclusive: 701 },
      onRangeChange,
    })
    const inPoint = container.querySelector<HTMLInputElement>('[aria-label="In point"]')!
    const outPoint = container.querySelector<HTMLInputElement>('[aria-label="Out point"]')!
    const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set

    expect([inPoint.min, inPoint.max]).toEqual(['0', '999'])
    expect([outPoint.min, outPoint.max]).toEqual(['0', '999'])

    await act(async () => {
      setValue?.call(inPoint, '300')
      inPoint.dispatchEvent(new Event('input', { bubbles: true }))
    })
    expect(onRangeChange).toHaveBeenLastCalledWith({
      startFrameIdx: 300,
      endFrameExclusive: 701,
    })

    await act(async () => {
      setValue?.call(outPoint, '799')
      outPoint.dispatchEvent(new Event('input', { bubbles: true }))
    })
    expect(onRangeChange).toHaveBeenLastCalledWith({
      startFrameIdx: 250,
      endFrameExclusive: 800,
    })

    await act(async () => inPoint.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'ArrowRight',
      bubbles: true,
    })))
    expect(onRangeChange).toHaveBeenLastCalledWith({
      startFrameIdx: 251,
      endFrameExclusive: 701,
    })

    await act(async () => outPoint.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'ArrowLeft',
      bubbles: true,
    })))
    expect(onRangeChange).toHaveBeenLastCalledWith({
      startFrameIdx: 250,
      endFrameExclusive: 700,
    })
    await act(async () => root.unmount())
  })

  it('dims excluded regions and keeps the selected segment visible but read-only outside Select', async () => {
    const { container, root } = await renderTimeline({
      frameCount: 1000,
      range: { startFrameIdx: 250, endFrameExclusive: 701 },
      rangeEditable: false,
    })

    expect(container.querySelector<HTMLElement>('[data-excluded="before"]')?.style.width).toBe('25%')
    expect(container.querySelector<HTMLElement>('[data-included-range]')?.style.width).toBe('45.1%')
    expect(container.querySelector<HTMLElement>('[data-excluded="after"]')?.style.width).toBe('29.9%')
    expect(container.querySelector<HTMLInputElement>('[aria-label="In point"]')?.disabled).toBe(true)
    expect(container.querySelector<HTMLInputElement>('[aria-label="Out point"]')?.disabled).toBe(true)
    expect(button(container, 'Set In').disabled).toBe(true)
    expect(button(container, 'Set Out').disabled).toBe(true)
    expect(button(container, 'Reset').disabled).toBe(true)
    expect(container.textContent).toContain('451 frames')
    await act(async () => root.unmount())
  })
})
