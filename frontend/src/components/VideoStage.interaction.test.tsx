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
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
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
          playbackLocked={false}
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

  it('ignores source and candidate clicks while selection is locked', async () => {
    const onSourceClick = vi.fn()
    const onCandidateConfirm = vi.fn()
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)

    await act(async () => root.render(
      <VideoStage
        src="/video.mp4"
        sourceWidth={400}
        sourceHeight={200}
        fps={30}
        frameCount={90}
        selection={null}
        track={[]}
        cropWindows={[]}
        candidates={[{ box: [50, 25, 150, 75], score: 0.9 }]}
        playbackLocked={false}
        selectionLocked
        onSourceClick={onSourceClick}
        onCandidateConfirm={onCandidateConfirm}
        onFrameChange={vi.fn()}
      />,
    ))
    const video = container.querySelector('video')!
    const pause = vi.spyOn(video, 'pause').mockImplementation(() => {})
    video.getBoundingClientRect = () => DOMRect.fromRect({ width: 400, height: 200 })

    await act(async () => video.dispatchEvent(new MouseEvent('click', {
      bubbles: true,
      clientX: 100,
      clientY: 50,
    })))

    expect(pause).not.toHaveBeenCalled()
    expect(onSourceClick).not.toHaveBeenCalled()
    expect(onCandidateConfirm).not.toHaveBeenCalled()
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
          playbackLocked={false}
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
          playbackLocked={false}
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

  it('returns and reports the exact media frame when paused', async () => {
    const onFrameChange = vi.fn()
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const stageRef = createRef<VideoStageHandle>()

    await act(async () => root.render(
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
        playbackLocked={false}
        onSourceClick={vi.fn()}
        onCandidateConfirm={vi.fn()}
        onFrameChange={onFrameChange}
      />,
    ))
    const video = container.querySelector('video')!
    video.currentTime = 37 / 30

    let pausedFrame: unknown
    await act(async () => { pausedFrame = stageRef.current?.pause() })

    expect(pausedFrame).toBe(37)
    expect(onFrameChange).toHaveBeenLastCalledWith(37)
    await act(async () => root.unmount())
  })

  it('restores the frozen frame across imperative and native navigation', async () => {
    const onFrameChange = vi.fn()
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const stageRef = createRef<VideoStageHandle>()
    const renderStage = (playbackLocked: boolean) => (
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
        playbackLocked={playbackLocked}
        onSourceClick={vi.fn()}
        onCandidateConfirm={vi.fn()}
        onFrameChange={onFrameChange}
      />
    )

    await act(async () => root.render(renderStage(false)))
    const video = container.querySelector('video')!
    video.currentTime = 37 / 30
    await act(async () => { stageRef.current?.pause() })
    await act(async () => root.render(renderStage(true)))

    await act(async () => {
      stageRef.current?.seekToFrame(60)
      stageRef.current?.stepFrames(1)
    })
    expect(video.currentTime).toBeCloseTo(37 / 30)

    video.currentTime = 2
    await act(async () => video.dispatchEvent(new Event('seeking', { bubbles: true })))
    await act(async () => video.dispatchEvent(new Event('seeked', { bubbles: true })))
    expect(video.currentTime).toBeCloseTo(37 / 30)
    expect(onFrameChange).toHaveBeenLastCalledWith(37)
    await act(async () => root.unmount())
  })

  it('pauses before reporting a source click', async () => {
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
          playbackLocked={false}
          onSourceClick={onSourceClick}
          onCandidateConfirm={vi.fn()}
          onFrameChange={vi.fn()}
        />,
      )
    })

    const video = container.querySelector('video')!
    const pause = vi.spyOn(video, 'pause').mockImplementation(() => {})
    const currentTimeRead = vi.fn(() => 1)
    Object.defineProperty(video, 'currentTime', {
      configurable: true,
      get: currentTimeRead,
      set: vi.fn(),
    })
    video.getBoundingClientRect = () => DOMRect.fromRect({ width: 400, height: 200 })

    await act(async () => {
      video.dispatchEvent(new MouseEvent('click', {
        bubbles: true,
        clientX: 100,
        clientY: 50,
      }))
    })

    expect(pause.mock.invocationCallOrder[0]).toBeLessThan(
      currentTimeRead.mock.invocationCallOrder[0],
    )
    expect(pause.mock.invocationCallOrder[0]).toBeLessThan(
      onSourceClick.mock.invocationCallOrder[0],
    )
    await act(async () => root.unmount())
  })

  it('pauses before confirming a candidate', async () => {
    const onCandidateConfirm = vi.fn()
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
          candidates={[{ box: [50, 25, 150, 75], score: 0.9 }]}
          playbackLocked={true}
          onSourceClick={vi.fn()}
          onCandidateConfirm={onCandidateConfirm}
          onFrameChange={vi.fn()}
        />,
      )
    })

    const video = container.querySelector('video')!
    const pause = vi.spyOn(video, 'pause').mockImplementation(() => {})
    const currentTimeRead = vi.fn(() => 1)
    Object.defineProperty(video, 'currentTime', {
      configurable: true,
      get: currentTimeRead,
      set: vi.fn(),
    })
    video.getBoundingClientRect = () => DOMRect.fromRect({ width: 400, height: 200 })

    await act(async () => {
      video.dispatchEvent(new MouseEvent('click', {
        bubbles: true,
        clientX: 100,
        clientY: 50,
      }))
    })

    expect(pause.mock.invocationCallOrder[0]).toBeLessThan(
      currentTimeRead.mock.invocationCallOrder[0],
    )
    expect(pause.mock.invocationCallOrder[0]).toBeLessThan(
      onCandidateConfirm.mock.invocationCallOrder[0],
    )
    await act(async () => root.unmount())
  })

  it('blocks imperative playback while locked', async () => {
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
          playbackLocked
          onSourceClick={vi.fn()}
          onCandidateConfirm={vi.fn()}
          onFrameChange={vi.fn()}
        />,
      )
    })

    const video = container.querySelector('video')!
    const play = vi.spyOn(video, 'play').mockResolvedValue()
    Object.defineProperty(video, 'paused', { configurable: true, value: true })

    await act(async () => stageRef.current?.togglePlayback())

    expect(play).not.toHaveBeenCalled()
    await act(async () => root.unmount())
  })

  it('immediately pauses native playback while locked', async () => {
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
          playbackLocked
          onSourceClick={vi.fn()}
          onCandidateConfirm={vi.fn()}
          onFrameChange={vi.fn()}
        />,
      )
    })

    const video = container.querySelector('video')!
    const pause = vi.spyOn(video, 'pause').mockImplementation(() => {})

    await act(async () => video.dispatchEvent(new Event('play', { bubbles: true })))

    expect(pause).toHaveBeenCalledOnce()
    await act(async () => root.unmount())
  })
})
