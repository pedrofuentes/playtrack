import { createElement } from 'react'
import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import { LibraryPanel } from './LibraryPanel'

it('renders saved tracks, exports, and cache maintenance', () => {
  const markup = renderToStaticMarkup(createElement(LibraryPanel, {
    library: { cacheBytes: 1024, videos: [{
      videoId: 'video-1', name: 'match.mp4', size: 2048, openedAt: '2026-07-16T00:00:00Z', sourceExists: true,
      sourceKind: 'path', path: '/match.mp4', metadata: { videoId: 'video-1', width: 320, height: 180, fps: 10, nbFrames: 4, duration: .4 },
      tracks: [{ jobId: 'track-1', anchorFrameIdx: 2, box: [1, 2, 3, 4], frameCount: 4, lostCount: 1, createdAt: '2026-07-16T00:00:00Z' }],
      exports: [{ exportId: 'export-1', videoId: 'video-1', trackJobId: 'track-1', params: { outWidth: 128, outHeight: 72 }, path: '/export.mp4', size: 512, createdAt: '2026-07-16T00:00:00Z', sourceExists: true }],
    }] },
    onOpenVideo: () => {}, onReExport: () => {}, onRefresh: () => {},
  }))
  expect(markup).toContain('match.mp4')
  expect(markup).toContain('Anchor 2 · 4 frames · 1 lost')
  expect(markup).toContain('128 × 72')
  expect(markup).toContain('Clear frame caches (0.0 MB)')
})
