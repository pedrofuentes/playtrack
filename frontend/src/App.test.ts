// @vitest-environment jsdom

import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const appMocks = vi.hoisted(() => ({
  play: vi.fn(),
  seekToFrame: vi.fn(),
  sourceClick: vi.fn(),
  stepFrames: vi.fn(),
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
      {
        playbackLocked,
        selectionLocked,
        onSourceClick,
      }: {
        playbackLocked: boolean
        selectionLocked: boolean
        onSourceClick: (point: { x: number; y: number }, frameIdx: number) => void
      },
      ref,
    ) {
      appMocks.playbackLocked = playbackLocked
      appMocks.selectionLocked = selectionLocked
      appMocks.sourceClick.mockImplementation(onSourceClick)
      useImperativeHandle(ref, () => ({
        play: appMocks.play,
        togglePlayback: appMocks.play,
        seekToFrame: appMocks.seekToFrame,
        stepFrames: appMocks.stepFrames,
      }))
      return createElement('div', { 'data-testid': 'video-stage' })
    }),
  }
})

import App, { JobPanel, libraryVideoName } from './App'
import { workspaceStage } from './workflow'

function workspace(overrides: Record<string, unknown> = {}) {
  return {
    video: null,
    videoName: null,
    currentFrame: 0,
    range: { startFrameIdx: 0, endFrameExclusive: 1 },
    selection: null,
    selectionLoading: false,
    selectionError: null,
    playerName: '',
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
    backendUnavailable: false,
    framing: false,
    exportJob: null,
    exportStarting: false,
    stage: 'select',
    videoSwitchLocked: false,
    openUpload: vi.fn(),
    openPath: vi.fn(),
    openLibraryVideo: vi.fn(),
    openLibraryPlayer: vi.fn(),
    retryConnection: vi.fn(),
    refreshLibrary: vi.fn(),
    selectAt: vi.fn(),
    setPlayerName: vi.fn(),
    setCurrentFrame: vi.fn(),
    setRange: vi.fn(),
    setRangeIn: vi.fn(),
    setRangeOut: vi.fn(),
    resetRange: vi.fn(),
    startTrack: vi.fn(),
    retryTrack: vi.fn(),
    beginFraming: vi.fn(),
    activeJobs: [],
    setCropWindows: vi.fn(),
    setExportJob: vi.fn(),
    beginExportSubmission: vi.fn().mockReturnValue(1),
    finishExportSubmission: vi.fn(),
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
  appMocks.play.mockClear()
  appMocks.seekToFrame.mockClear()
  appMocks.sourceClick.mockReset()
  appMocks.stepFrames.mockClear()
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
  expect(markup).toContain('Upload video')
  expect(markup).toContain('Upload a video')
  expect(markup.toLowerCase()).not.toContain('panoramic')
  expect(markup).not.toContain('Open video')
  expect(markup).not.toContain('Recent videos')
  expect(markup).not.toContain('Virtual camera export')
  expect(markup).not.toContain('Last source click')
})

it('renders cached-shell guidance and retries connectivity without opening a video', async () => {
  const retry = vi.fn()
  const openPath = vi.fn()
  appMocks.workspace = workspace({
    backendUnavailable: true,
    openError: 'The PlayTrack server is not responding.',
    retryConnection: retry,
    openPath,
  })
  const container = document.createElement('div')
  const root = createRoot(container)

  await act(async () => root.render(createElement(App)))

  expect(container.textContent).toContain('PlayTrack server is offline')
  expect(container.textContent).toContain('Start the local PlayTrack server')
  const retryButton = [...container.querySelectorAll('button')]
    .find((button) => button.textContent === 'Retry connection')!
  await act(async () => retryButton.click())
  expect(retry).toHaveBeenCalledOnce()
  expect(openPath).not.toHaveBeenCalled()
  await act(async () => root.unmount())
})

it.each([
  ['selection loading', { selectionLoading: true }],
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

it('locks player selection while reviewing', async () => {
  const state = { currentFrame: 40, range: { startFrameIdx: 30, endFrameExclusive: 60 }, stage: 'review' }
  appMocks.workspace = openedWorkspace(state)
  const container = document.createElement('div')
  const root = createRoot(container)

  await act(async () => root.render(createElement(App)))

  expect(appMocks.selectionLocked).toBe(true)
  await act(async () => root.unmount())
})

it('routes an outside-range click to workspace validation', async () => {
  const selectAt = vi.fn()
  appMocks.workspace = openedWorkspace({
    currentFrame: 20,
    range: { startFrameIdx: 30, endFrameExclusive: 60 },
    selectAt,
  })
  const container = document.createElement('div')
  const root = createRoot(container)

  await act(async () => root.render(createElement(App)))
  expect(appMocks.selectionLocked).toBe(false)
  act(() => appMocks.sourceClick({ x: 100, y: 50 }, 20))
  expect(selectAt).toHaveBeenCalledWith({ x: 100, y: 50 }, 20)
  await act(async () => root.unmount())
})

it.each([
  ['selection loading', { selectionLoading: true }],
  ['confirmed selection', { selection: { box: [1, 2, 3, 4], score: 0.9, maskPng: '' } }],
])('blocks ArrowRight frame stepping during %s', async (_label, selectionState) => {
  appMocks.workspace = openedWorkspace(selectionState)
  const container = document.createElement('div')
  const root = createRoot(container)

  await act(async () => root.render(createElement(App)))
  await act(async () => {
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
  })

  expect(appMocks.stepFrames).not.toHaveBeenCalled()
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

it('locks selection, range editing, and Enter tracking while an open is pending', async () => {
  const startTrack = vi.fn()
  appMocks.workspace = openedWorkspace({
    loading: true,
    selection: { box: [1, 2, 3, 4], score: 0.9, maskPng: '' },
    startTrack,
  })
  const container = document.createElement('div')
  const root = createRoot(container)

  await act(async () => root.render(createElement(App)))

  const button = (label: string) => [...container.querySelectorAll('button')]
    .find((item) => item.textContent === label)
  expect(appMocks.selectionLocked).toBe(true)
  expect(button('Set In')?.disabled).toBe(true)
  expect(button('Track player')?.disabled).toBe(true)
  expect(button('Choose a different player')?.disabled).toBe(true)
  expect(container.querySelector<HTMLInputElement>('.player-name-field input')?.disabled).toBe(true)

  await act(async () => {
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  })
  expect(startTrack).not.toHaveBeenCalled()
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

it('reports tracking progress over the selected range', () => {
  appMocks.workspace = openedWorkspace({
    video: {
      videoId: 'video-1', name: 'game.mp4', width: 400, height: 200,
      fps: 30, nbFrames: 930, duration: 31,
    },
    range: { startFrameIdx: 100, endFrameExclusive: 200 },
    stage: 'track',
    trackJob: {
      jobId: 'track-1',
      state: 'running',
      progress: 0.5,
      message: 'tracking',
      track: Array.from({ length: 50 }, (_value, index) => ({
        frameIdx: 100 + index,
        box: [1, 2, 3, 4],
        center: [2, 3],
        lost: false,
      })),
    },
  })

  const markup = renderToStaticMarkup(createElement(App))
  expect(markup).toContain('50 of 100 frames')
})

it('keeps Library search visible while its upload controls start collapsed', async () => {
  const container = document.createElement('div')
  const root = createRoot(container)

  await act(async () => root.render(createElement(App)))
  await act(async () => container.querySelector<HTMLButtonElement>('button[title="Library"]')?.click())

  const upload = container.querySelector<HTMLDetailsElement>('.library-upload-disclosure')
  expect(upload?.open).toBe(false)
  expect(upload?.querySelector('summary')?.textContent).toBe('Upload a new video')
  expect(container.querySelector<HTMLInputElement>('.library-search input')).not.toBeNull()
  await act(async () => root.unmount())
})

it('disables Library opens while any workspace open is loading', async () => {
  const saved = {
    videoId: 'saved-video',
    name: 'saved.mp4',
    sourceKind: 'path',
    path: '/saved.mp4',
    metadata: {
      videoId: 'saved-video', width: 400, height: 200,
      fps: 30, nbFrames: 90, duration: 3,
    },
    size: 100,
    openedAt: null,
    sourceExists: true,
    tracks: [],
    exports: [],
  }
  appMocks.workspace = openedWorkspace({
    loading: true,
    library: { videos: [saved], cacheBytes: 0 },
  })
  const container = document.createElement('div')
  const root = createRoot(container)

  await act(async () => root.render(createElement(App)))
  await act(async () => container.querySelector<HTMLButtonElement>('button[title="Library"]')?.click())

  const openSource = [...container.querySelectorAll('button')]
    .find((item) => item.textContent === 'Open')
  expect(openSource?.disabled).toBe(true)
  await act(async () => root.unmount())
})

it('disables Library mutations and cache clearing during active jobs', async () => {
  const saved = {
    videoId: 'saved-video',
    name: 'saved.mp4',
    sourceKind: 'path',
    path: '/saved.mp4',
    metadata: {
      videoId: 'saved-video', width: 400, height: 200,
      fps: 30, nbFrames: 90, duration: 3,
    },
    size: 100,
    openedAt: null,
    sourceExists: true,
    tracks: [],
    exports: [],
  }
  appMocks.workspace = openedWorkspace({
    videoSwitchLocked: true,
    library: { videos: [saved], cacheBytes: 0 },
  })
  const container = document.createElement('div')
  const root = createRoot(container)

  await act(async () => root.render(createElement(App)))
  await act(async () => container.querySelector<HTMLButtonElement>('button[title="Library"]')?.click())
  const namedButton = (label: string) => [...container.querySelectorAll('button')]
    .find((item) => item.textContent === label)
  expect(namedButton('Rename')?.disabled).toBe(true)
  expect(namedButton('Delete source')?.disabled).toBe(true)

  await act(async () => container.querySelector<HTMLButtonElement>('button[title="Settings"]')?.click())
  expect(namedButton('Clear frame cache')?.disabled).toBe(true)
  await act(async () => root.unmount())
})

describe('JobPanel', () => {
  const foreign = {
    jobId: 'track-elsewhere',
    kind: 'track' as const,
    state: 'running' as const,
    progress: 0.9,
    message: 'Tracking forward',
  }

  it('lists a tracking job this page did not start', () => {
    const markup = renderToStaticMarkup(createElement(JobPanel, {
      trackJob: null,
      exportJob: null,
      frameCount: 0,
      activeJobs: [foreign],
    }))

    expect(markup).toContain('Tracking forward')
    expect(markup).toContain('90%')
    expect(markup).not.toContain('No tracking or export job yet')
  })

  it('reports an empty surface only when the server has no work either', () => {
    const markup = renderToStaticMarkup(createElement(JobPanel, {
      trackJob: null,
      exportJob: null,
      frameCount: 0,
      activeJobs: [],
    }))

    expect(markup).toContain('No tracking or export job yet')
  })

  it('does not list this page\'s own job a second time', () => {
    const markup = renderToStaticMarkup(createElement(JobPanel, {
      trackJob: {
        jobId: foreign.jobId,
        state: 'running' as const,
        progress: 0.9,
        message: 'Tracking forward',
        track: [],
      },
      exportJob: null,
      frameCount: 100,
      activeJobs: [foreign],
    }))

    expect(markup.match(/Tracking forward/g)).toHaveLength(1)
  })

  it('counts actual tracked frames instead of weighted overall progress', () => {
    const markup = renderToStaticMarkup(createElement(JobPanel, {
      trackJob: {
        jobId: 'track-1',
        state: 'running' as const,
        progress: 0.08,
        message: 'Loading frames 80 of 100',
        track: [
          { frameIdx: 1, box: [1, 2, 3, 4] as const, center: [2, 3] as const, lost: false },
          { frameIdx: 2, box: [1, 2, 3, 4] as const, center: [2, 3] as const, lost: false },
          { frameIdx: 3, box: [1, 2, 3, 4] as const, center: [2, 3] as const, lost: false },
        ],
      },
      exportJob: null,
      frameCount: 100,
      activeJobs: [],
    }))

    expect(markup).toContain('3 / 100 frames')
    expect(markup).not.toContain('8 / 100 frames')
  })
})
