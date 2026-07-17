// @vitest-environment jsdom

import { act, createRef } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { type VideoStageHandle, VideoStage } from './VideoStage'

class ResizeObserverStub {
  observe() {}
  disconnect() {}
}

function pointerEvent(type: string, x: number, y: number): Event {
  const event = new MouseEvent(type, { bubbles: true, clientX: x, clientY: y })
  Object.defineProperty(event, 'pointerId', { value: 1 })
  return event
}

describe('VideoStage pointer interactions', () => {
  beforeEach(() => {
    vi.stubGlobal('ResizeObserver', ResizeObserverStub)
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
    Object.defineProperty(HTMLElement.prototype, 'setPointerCapture', {
      configurable: true,
      value: vi.fn(),
    })
    Object.defineProperty(HTMLElement.prototype, 'releasePointerCapture', {
      configurable: true,
      value: vi.fn(),
    })
    Object.defineProperty(HTMLElement.prototype, 'hasPointerCapture', {
      configurable: true,
      value: vi.fn().mockReturnValue(true),
    })
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
    vi.spyOn(console, 'info').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    document.body.innerHTML = ''
  })

  it('selects on a motionless click while zoomed without taking pointer capture', async () => {
    const onSourceClick = vi.fn()
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)

    await act(async () => {
      root.render(
        <VideoStage
          src="/video.mp4"
          sourceWidth={400}
          sourceHeight={200}
          fps={30}
          frameCount={90}
          selection={null}
          track={[]}
          cropWindows={[]}
          candidates={[]}
          onSourceClick={onSourceClick}
          onCandidateConfirm={vi.fn()}
          onFrameChange={vi.fn()}
        />,
      )
    })

    const stage = container.querySelector<HTMLElement>('.video-stage')!
    const transform = container.querySelector<HTMLElement>('.video-transform')!
    const video = container.querySelector('video')!
    const zoomIn = container.querySelector<HTMLButtonElement>('[aria-label="Zoom in"]')!
    const setPointerCapture = vi.mocked(HTMLElement.prototype.setPointerCapture)
    stage.getBoundingClientRect = () => DOMRect.fromRect({ width: 400, height: 200 })
    video.getBoundingClientRect = () => DOMRect.fromRect({ width: 600, height: 300 })

    await act(async () => zoomIn.click())
    await act(async () => {
      video.dispatchEvent(pointerEvent('pointerdown', 120, 60))
      video.dispatchEvent(pointerEvent('pointerup', 120, 60))
      const clickTarget = setPointerCapture.mock.calls.length > 0 ? transform : video
      clickTarget.dispatchEvent(new MouseEvent('click', {
        bubbles: true,
        clientX: 120,
        clientY: 60,
      }))
    })

    expect(setPointerCapture).not.toHaveBeenCalled()
    expect(onSourceClick).toHaveBeenCalledOnce()
    await act(async () => root.unmount())
  })

  it('suppresses the video click emitted after a pan drag', async () => {
    const onSourceClick = vi.fn()
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)

    await act(async () => {
      root.render(
        <VideoStage
          src="/video.mp4"
          sourceWidth={400}
          sourceHeight={200}
          fps={30}
          frameCount={90}
          selection={null}
          track={[]}
          cropWindows={[]}
          candidates={[]}
          onSourceClick={onSourceClick}
          onCandidateConfirm={vi.fn()}
          onFrameChange={vi.fn()}
        />,
      )
    })

    const stage = container.querySelector<HTMLElement>('.video-stage')!
    const transform = container.querySelector<HTMLElement>('.video-transform')!
    const video = container.querySelector('video')!
    const zoomIn = container.querySelector<HTMLButtonElement>('[aria-label="Zoom in"]')!
    const setPointerCapture = vi.mocked(HTMLElement.prototype.setPointerCapture)
    stage.getBoundingClientRect = () => DOMRect.fromRect({ width: 400, height: 200 })
    video.getBoundingClientRect = () => DOMRect.fromRect({ width: 800, height: 400 })

    await act(async () => zoomIn.click())
    await act(async () => {
      transform.dispatchEvent(pointerEvent('pointerdown', 100, 80))
      transform.dispatchEvent(pointerEvent('pointermove', 112, 80))
      transform.dispatchEvent(pointerEvent('pointerup', 112, 80))
      video.dispatchEvent(new MouseEvent('click', {
        bubbles: true,
        clientX: 112,
        clientY: 80,
      }))
    })

    expect(setPointerCapture).toHaveBeenCalledOnce()
    expect(onSourceClick).not.toHaveBeenCalled()
    await act(async () => root.unmount())
  })

  it('exposes frame-accurate seek and playback controls', async () => {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const stageRef = createRef<VideoStageHandle>()

    await act(async () => {
      root.render(
        <VideoStage
          ref={stageRef}
          src="/video.mp4"
          sourceWidth={400}
          sourceHeight={200}
          fps={30}
          frameCount={90}
          selection={null}
          track={[]}
          cropWindows={[]}
          candidates={[]}
          onSourceClick={vi.fn()}
          onCandidateConfirm={vi.fn()}
          onFrameChange={vi.fn()}
        />,
      )
    })

    const video = container.querySelector('video')!
    const play = vi.spyOn(video, 'play').mockResolvedValue()
    const pause = vi.spyOn(video, 'pause').mockImplementation(() => {})

    await act(async () => stageRef.current?.seekToFrame(30))
    expect(video.currentTime).toBe(1)
    await act(async () => stageRef.current?.stepFrames(-15))
    expect(video.currentTime).toBe(0.5)

    Object.defineProperty(video, 'paused', { configurable: true, value: true })
    await act(async () => stageRef.current?.togglePlayback())
    expect(play).toHaveBeenCalledOnce()
    Object.defineProperty(video, 'paused', { configurable: true, value: false })
    await act(async () => stageRef.current?.togglePlayback())
    expect(pause).toHaveBeenCalledOnce()
    await act(async () => root.unmount())
  })
})
