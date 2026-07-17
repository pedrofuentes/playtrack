// @vitest-environment jsdom

import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const appMocks = vi.hoisted(() => ({
  pause: vi.fn(),
  play: vi.fn(),
  playbackLocked: false,
  selectionLocked: false,
  workspace: null as unknown,
}))

vi.mock('./hooks/useWorkspace', () => ({
  useWorkspace: () => appMocks.workspace,
}))

vi.mock('./components/VideoStage', async () => {
  const { createElement, forwardRef, useImperativeHandle } = await import('react')
  return {
    VideoStage: forwardRef(function MockVideoStage(
      { playbackLocked, selectionLocked }: { playbackLocked: boolean; selectionLocked: boolean },
      ref,
    ) {
      appMocks.playbackLocked = playbackLocked
      appMocks.selectionLocked = selectionLocked
      useImperativeHandle(ref, () => ({
        pause: appMocks.pause,
        play: appMocks.play,
        togglePlayback: appMocks.play,
        seekToFrame: vi.fn(),
        stepFrames: vi.fn(),
      }))
      return createElement('div', { 'data-testid': 'video-stage' })
    }),
  }
})

import App, { libraryVideoName } from './App'
import { workspaceStage } from './workflow'

function workspace(overrides: Record<string, unknown> = {}) {
  return {
    video: null,
    videoName: null,
    currentFrame: 0,
    range: { startFrameIdx: 0, endFrameExclusive: 1 },
    selection: null,
    selectionKind: 'click',
    selectionLoading: false,
    selectionError: null,
    candidates: [],
    playerName: '',
    features: { textSelection: { enabled: false, reason: '' } },
    library: { videos: [], cacheBytes: 0 },
    trackJob: null,
    trackMessage: null,
    trackError: null,
    trackStarting: false,
    trackStartedAt: null,
    cropWindows: [],
    loading: false,
    loadingLabel: '',
    openError: null,
    framing: false,
    exportJob: null,
    stage: 'select',
    videoSwitchLocked: false,
    openUpload: vi.fn(),
    openPath: vi.fn(),
    openLibraryVideo: vi.fn(),
    openLibraryPlayer: vi.fn(),
    refreshLibrary: vi.fn(),
    selectAt: vi.fn(),
    selectByDescription: vi.fn(),
    confirmCandidate: vi.fn(),
    setPlayerName: vi.fn(),
    setCurrentFrame: vi.fn(),
    setRange: vi.fn(),
    setRangeIn: vi.fn(),
    setRangeOut: vi.fn(),
    resetRange: vi.fn(),
    startTrack: vi.fn(),
    retryTrack: vi.fn(),
    beginFraming: vi.fn(),
    setCropWindows: vi.fn(),
    setExportJob: vi.fn(),
    resetSelection: vi.fn(),
    clearCaches: vi.fn(),
    ...overrides,
  }
}

function openedWorkspace(overrides: Record<string, unknown> = {}) {
  return workspace({
    video: {
      videoId: 'video-1',
      name: 'game.mp4',
      width: 400,
      height: 200,
      fps: 30,
      nbFrames: 90,
      duration: 3,
    },
    videoName: 'game.mp4',
    range: { startFrameIdx: 0, endFrameExclusive: 90 },
    ...overrides,
  })
}

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  appMocks.pause.mockClear()
  appMocks.play.mockClear()
  appMocks.playbackLocked = false
  appMocks.selectionLocked = false
  appMocks.workspace = workspace()
})

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('workspaceStage', () => {
  it('advances from selection to tracking to review', () => {
    expect(workspaceStage(null, null, false)).toBe('select')
    expect(
      workspaceStage(
        { box: [1, 2, 3, 4], maskPng: '', score: 0.9 },
        {
          jobId: 'track-1',
          state: 'running',
          progress: 0.5,
          message: 'tracking',
          track: [],
        },
        false,
      ),
    ).toBe('track')
    expect(
      workspaceStage(
        null,
        {
          jobId: 'track-1',
          state: 'completed',
          progress: 1,
          message: 'done',
          track: [],
        },
        false,
      ),
    ).toBe('review')
  })
})

it('uses the library display name when opening a saved upload', () => {
  expect(libraryVideoName({ name: 'Championship Final.mp4' } as never)).toBe(
    'Championship Final.mp4',
  )
})

it('renders the pro-editor shell without expanded secondary surfaces', () => {
  const markup = renderToStaticMarkup(createElement(App))
  expect(markup).toContain('class="workspace-shell"')
  expect(markup).toContain('aria-label="Editor tools"')
  expect(markup).toContain('Open video')
  expect(markup).not.toContain('Recent videos')
  expect(markup).not.toContain('Virtual camera export')
  expect(markup).not.toContain('Last source click')
})

it('pauses the video before starting text selection', async () => {
  const selectByDescription = vi.fn()
  appMocks.workspace = openedWorkspace({
    features: { textSelection: { enabled: true, reason: '' } },
    selectByDescription,
  })
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)

  await act(async () => root.render(createElement(App)))
  const describeButton = container.querySelector<HTMLButtonElement>('[data-method="describe"]')!
  await act(async () => describeButton.click())
  const input = container.querySelector<HTMLInputElement>('#player-description')!
  const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  await act(async () => {
    setValue.call(input, 'white jersey')
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
  const form = container.querySelector<HTMLFormElement>('.text-selection-form')!
  await act(async () => form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true })))

  expect(appMocks.pause.mock.invocationCallOrder[0]).toBeLessThan(
    selectByDescription.mock.invocationCallOrder[0],
  )
  await act(async () => root.unmount())
  container.remove()
})

it.each([
  ['selection loading', { selectionLoading: true }],
  ['text candidates', { candidates: [{ box: [1, 2, 3, 4], score: 0.9 }] }],
  ['confirmed selection', { selection: { box: [1, 2, 3, 4], score: 0.9, maskPng: '' } }],
])('locks playback during %s', async (_label, selectionState) => {
  appMocks.workspace = openedWorkspace({
    ...selectionState,
  })
  const container = document.createElement('div')
  const root = createRoot(container)

  await act(async () => root.render(createElement(App)))

  expect(appMocks.playbackLocked).toBe(true)
  await act(async () => root.unmount())
})

it('unlocks reset selection without starting playback', async () => {
  const resetSelection = vi.fn()
  const selected = { box: [1, 2, 3, 4], score: 0.9, maskPng: '' }
  appMocks.workspace = openedWorkspace({ selection: selected, resetSelection })
  const container = document.createElement('div')
  const root = createRoot(container)

  await act(async () => root.render(createElement(App)))
  expect(appMocks.playbackLocked).toBe(true)

  const resetButton = Array.from(container.querySelectorAll('button')).find(
    (button) => button.textContent === 'Choose a different player',
  )!
  await act(async () => resetButton.click())
  appMocks.workspace = openedWorkspace({ resetSelection })
  await act(async () => root.render(createElement(App)))

  expect(resetSelection).toHaveBeenCalledOnce()
  expect(appMocks.playbackLocked).toBe(false)
  expect(appMocks.play).not.toHaveBeenCalled()
  await act(async () => root.unmount())
})

it.each(['track', 'review', 'export'])('leaves %s playback unlocked', async (stage) => {
  appMocks.workspace = openedWorkspace({
    stage,
    selection: { box: [1, 2, 3, 4], score: 0.9, maskPng: '' },
  })
  const container = document.createElement('div')
  const root = createRoot(container)

  await act(async () => root.render(createElement(App)))

  expect(appMocks.playbackLocked).toBe(false)
  await act(async () => root.unmount())
})

it.each([
  ['outside the range in Select', { currentFrame: 20, range: { startFrameIdx: 30, endFrameExclusive: 60 }, stage: 'select' }],
  ['while reviewing', { currentFrame: 40, range: { startFrameIdx: 30, endFrameExclusive: 60 }, stage: 'review' }],
])('locks player selection %s', async (_label, state) => {
  appMocks.workspace = openedWorkspace(state)
  const container = document.createElement('div')
  const root = createRoot(container)

  await act(async () => root.render(createElement(App)))

  expect(appMocks.selectionLocked).toBe(true)
  await act(async () => root.unmount())
})

it('wires editable ranges to the timeline only during Select', async () => {
  const setRange = vi.fn()
  appMocks.workspace = openedWorkspace({
    currentFrame: 30,
    range: { startFrameIdx: 10, endFrameExclusive: 60 },
    setRange,
  })
  const container = document.createElement('div')
  const root = createRoot(container)

  await act(async () => root.render(createElement(App)))
  const setIn = [...container.querySelectorAll('button')]
    .find((item) => item.textContent === 'Set In')!
  await act(async () => setIn.click())
  expect(setRange).toHaveBeenCalledWith({ startFrameIdx: 30, endFrameExclusive: 60 })

  appMocks.workspace = openedWorkspace({
    currentFrame: 30,
    range: { startFrameIdx: 10, endFrameExclusive: 60 },
    stage: 'review',
    setRange,
  })
  await act(async () => root.render(createElement(App)))
  expect([...container.querySelectorAll('button')]
    .find((item) => item.textContent === 'Set In')?.disabled).toBe(true)

  appMocks.workspace = openedWorkspace({
    currentFrame: 30,
    range: { startFrameIdx: 10, endFrameExclusive: 60 },
    stage: 'select',
    trackStarting: true,
    setRange,
  })
  await act(async () => root.render(createElement(App)))
  expect([...container.querySelectorAll('button')]
    .find((item) => item.textContent === 'Set In')?.disabled).toBe(true)
  expect(appMocks.selectionLocked).toBe(true)
  await act(async () => root.unmount())
})

it('calculates track coverage over the selected range', async () => {
  appMocks.workspace = openedWorkspace({
    range: { startFrameIdx: 10, endFrameExclusive: 20 },
    stage: 'review',
    trackJob: {
      jobId: 'track-1',
      state: 'completed',
      progress: 1,
      message: 'done',
      track: Array.from({ length: 5 }, (_value, index) => ({
        frameIdx: 10 + index,
        box: [1, 2, 3, 4],
        center: [2, 3],
        lost: false,
      })),
    },
  })

  const markup = renderToStaticMarkup(createElement(App))
  expect(markup).toContain('50% coverage')
})
