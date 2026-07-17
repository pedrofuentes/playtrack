// @vitest-environment jsdom

import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import type { LibraryResponse, LibraryVideo } from '../api'
import { LibraryPanel } from './LibraryPanel'

function savedVideo(videoId: string, name: string, sourceKind: 'path' | 'upload'): LibraryVideo {
  return {
    videoId,
    name,
    size: 2048,
    openedAt: '2026-07-16T00:00:00Z',
    sourceExists: true,
    sourceKind,
    path: `/${name}`,
    metadata: { videoId, width: 320, height: 180, fps: 10, nbFrames: 4, duration: .4 },
    tracks: [{ jobId: `${videoId}-track`, anchorFrameIdx: 2, box: [1, 2, 3, 4], frameCount: 4, lostCount: 1, createdAt: '2026-07-16T00:00:00Z' }],
    exports: [{ exportId: `${videoId}-export`, videoId, trackJobId: `${videoId}-track`, params: { outWidth: 128, outHeight: 72 }, path: '/export.mp4', size: 512, createdAt: '2026-07-16T00:00:00Z', sourceExists: true }],
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
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it('filters saved videos and labels source ownership', async () => {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  await act(async () => root.render(
    <LibraryPanel
      library={library}
      openingDisabled={false}
      onOpenVideo={vi.fn()}
      onReExport={vi.fn()}
      onRefresh={vi.fn()}
    />,
  ))

  expect(container.textContent).toContain('Registered path')
  expect(container.textContent).toContain('Uploaded copy')
  const search = container.querySelector<HTMLInputElement>('input[type="search"]')!
  await act(async () => {
    const valueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
    valueSetter?.call(search, 'practice')
    search.dispatchEvent(new Event('input', { bubbles: true }))
  })
  expect(container.textContent).not.toContain('Championship Final.mp4')
  expect(container.textContent).toContain('Practice Wide Angle.mp4')
  await act(async () => root.unmount())
})

it('locks opening and re-export without hiding downloads', async () => {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  await act(async () => root.render(
    <LibraryPanel
      library={{ ...library, videos: [library.videos[0]] }}
      openingDisabled
      onOpenVideo={vi.fn()}
      onReExport={vi.fn()}
      onRefresh={vi.fn()}
    />,
  ))

  const buttons = [...container.querySelectorAll('button')]
  expect(buttons.find((button) => button.textContent === 'Open')?.disabled).toBe(true)
  expect(buttons.find((button) => button.textContent === 'Re-export')?.disabled).toBe(true)
  expect(container.querySelector('a[download]')).not.toBeNull()
  expect(container.textContent).not.toContain('Clear frame caches')
  await act(async () => root.unmount())
})
