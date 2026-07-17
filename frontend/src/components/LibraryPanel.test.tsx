// @vitest-environment jsdom

import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import type { LibraryResponse, LibraryVideo } from '../api'
import { LibraryPanel } from './LibraryPanel'

const apiMocks = vi.hoisted(() => ({
  deleteLibraryExport: vi.fn().mockResolvedValue(undefined),
  deleteLibraryTrack: vi.fn().mockResolvedValue(undefined),
  deleteLibraryVideo: vi.fn().mockResolvedValue(undefined),
  renameLibraryPlayer: vi.fn().mockResolvedValue({ jobId: 'video-1-track', name: 'Goalie' }),
  renameLibrarySource: vi.fn().mockResolvedValue({ videoId: 'video-1', name: 'Championship Final' }),
}))

vi.mock('../api', async (importOriginal) => ({
  ...await importOriginal<typeof import('../api')>(),
  ...apiMocks,
}))

function savedVideo(videoId: string, name: string, sourceKind: 'path' | 'upload'): LibraryVideo {
  return {
    videoId,
    name,
    size: 2048,
    openedAt: '2026-07-16T00:00:00Z',
    sourceExists: true,
    sourceKind,
    path: `/${name}`,
    metadata: { videoId, width: 320, height: 180, fps: 25, nbFrames: 1000, duration: 40 },
    tracks: [{ name: 'White 19', jobId: `${videoId}-track`, anchorFrameIdx: 250, box: [1, 2, 3, 4], startFrameIdx: 250, endFrameExclusive: 701, frameCount: 451, lostCount: 1, createdAt: '2026-07-16T00:00:00Z' }],
    exports: [{ exportId: `${videoId}-export`, videoId, trackJobId: `${videoId}-track`, params: { outWidth: 128, outHeight: 72, zoom: 2 }, path: '/export.mp4', size: 512, createdAt: '2026-07-16T00:00:00Z', sourceExists: true }],
  }
}

const library: LibraryResponse = {
  cacheBytes: 1024,
  videos: [
    savedVideo('video-1', 'Championship Final.mp4', 'path'),
    savedVideo('video-2', 'Practice Wide Angle.mp4', 'upload'),
  ],
}

beforeEach(() => vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true))
afterEach(() => {
  document.body.innerHTML = ''
  vi.clearAllMocks()
  vi.unstubAllGlobals()
})

async function renderLibrary(overrides: Partial<Parameters<typeof LibraryPanel>[0]> = {}) {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  const props = {
    library,
    openingDisabled: false,
    onOpenVideo: vi.fn(),
    onOpenPlayer: vi.fn().mockResolvedValue(true),
    onRefresh: vi.fn(),
    ...overrides,
  }
  await act(async () => root.render(<LibraryPanel {...props} />))
  return { container, root, props }
}

function button(container: HTMLElement, name: string) {
  return [...container.querySelectorAll('button')].find((item) => item.textContent?.trim() === name)!
}

it('separates sources, named players, and exports into tabs', async () => {
  const { container, root } = await renderLibrary()
  expect(container.textContent).toContain('Championship Final.mp4')
  expect(container.textContent).not.toContain('White 19')

  await act(async () => button(container, 'Players').click())
  expect(container.textContent).toContain('White 19')
  expect(container.textContent).toContain('Championship Final.mp4')
  expect(container.textContent).toContain('Open player')
  expect(container.textContent).toContain('00:10–00:28 · 18.0 sec · 451 frames')
  expect(container.textContent).not.toContain('Re-export')

  await act(async () => button(container, 'Exports').click())
  expect(container.textContent).toContain('White 19')
  expect(container.textContent).toContain('128 × 72')
  expect(container.querySelector('a[download]')).not.toBeNull()
  expect(container.textContent).not.toContain('Open player')
  await act(async () => root.unmount())
})

it('shows legacy players without range fields as full-video ranges', async () => {
  const current = savedVideo('legacy', 'Legacy.mp4', 'path')
  const legacyPlayer = { ...current.tracks[0] } as Partial<(typeof current.tracks)[number]>
  delete legacyPlayer.startFrameIdx
  delete legacyPlayer.endFrameExclusive
  current.tracks = [legacyPlayer as (typeof current.tracks)[number]]
  const { container, root } = await renderLibrary({
    library: { cacheBytes: 0, videos: [current] },
  })

  await act(async () => button(container, 'Players').click())
  expect(container.textContent).toContain('00:00–00:39 · 40.0 sec · 1000 frames')
  await act(async () => root.unmount())
})

it('labels Out with the final included frame while duration uses the frame count', async () => {
  const current = savedVideo('low-fps', 'Low FPS.mp4', 'path')
  current.metadata.fps = 2
  current.metadata.nbFrames = 10
  current.tracks = [{
    ...current.tracks[0],
    anchorFrameIdx: 2,
    startFrameIdx: 2,
    endFrameExclusive: 4,
    frameCount: 2,
  }]
  const { container, root } = await renderLibrary({
    library: { cacheBytes: 0, videos: [current] },
  })

  await act(async () => button(container, 'Players').click())
  expect(container.textContent).toContain('00:01–00:01 · 1.0 sec · 2 frames')
  await act(async () => root.unmount())
})

it('searches only the active tab and opens a saved player', async () => {
  const onOpenPlayer = vi.fn().mockResolvedValue(true)
  const { container, root } = await renderLibrary({ onOpenPlayer })
  await act(async () => button(container, 'Players').click())
  const search = container.querySelector<HTMLInputElement>('input[type="search"]')!
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
    setter?.call(search, 'practice')
    search.dispatchEvent(new Event('input', { bubbles: true }))
  })
  expect(container.textContent).not.toContain('Championship Final.mp4')
  expect(container.textContent).toContain('Practice Wide Angle.mp4')

  await act(async () => button(container, 'Open player').click())
  expect(onOpenPlayer).toHaveBeenCalledWith(library.videos[1], library.videos[1].tracks[0])
  await act(async () => root.unmount())
})

it('renames a player inline and keeps missing sources deletable', async () => {
  const missing = { ...library.videos[0], sourceExists: false }
  const { container, root, props } = await renderLibrary({ library: { ...library, videos: [missing] } })
  await act(async () => button(container, 'Players').click())
  expect(button(container, 'Open player').disabled).toBe(true)
  await act(async () => button(container, 'Rename').click())
  const input = container.querySelector<HTMLInputElement>('input[aria-label="Player name"]')!
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
    setter?.call(input, 'Goalie')
    input.dispatchEvent(new Event('input', { bubbles: true }))
    button(container, 'Save').click()
    await Promise.resolve()
  })
  expect(apiMocks.renameLibraryPlayer).toHaveBeenCalledWith('video-1-track', 'Goalie')
  expect(props.onRefresh).toHaveBeenCalled()
  expect(button(container, 'Delete').disabled).toBe(false)
  await act(async () => root.unmount())
})

it('renames a source inline, refreshes the library, and keeps player rename state independent', async () => {
  const { container, root, props } = await renderLibrary({
    library: { ...library, videos: [library.videos[0]] },
  })
  await act(async () => button(container, 'Rename').click())
  const sourceInput = container.querySelector<HTMLInputElement>('input[aria-label="Source name"]')!
  const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
  await act(async () => {
    setValue?.call(sourceInput, 'Championship Final')
    sourceInput.dispatchEvent(new Event('input', { bubbles: true }))
  })

  await act(async () => button(container, 'Players').click())
  await act(async () => button(container, 'Rename').click())
  expect(container.querySelector<HTMLInputElement>('input[aria-label="Player name"]')?.value).toBe('White 19')

  await act(async () => button(container, 'Sources').click())
  expect(container.querySelector<HTMLInputElement>('input[aria-label="Source name"]')?.value).toBe('Championship Final')
  await act(async () => {
    button(container, 'Save').click()
    await Promise.resolve()
  })
  expect(apiMocks.renameLibrarySource).toHaveBeenCalledWith('video-1', 'Championship Final')
  expect(props.onRefresh).toHaveBeenCalled()
  await act(async () => root.unmount())
})
