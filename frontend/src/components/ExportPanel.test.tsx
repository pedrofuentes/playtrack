import { createRef } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import { type ExportPanelHandle, EXPORT_PRESETS, ExportPanel } from './ExportPanel'

describe('EXPORT_PRESETS', () => {
  it('keeps 720p as the default and supports 1080p and custom output', () => {
    expect(EXPORT_PRESETS).toEqual([
      { key: '1920x1080', label: '1080p', detail: '1920 × 1080', width: 1920, height: 1080 },
      { key: '1280x720', label: '720p', detail: '1280 × 720', width: 1280, height: 720 },
      { key: 'custom', label: 'Custom', detail: 'Even dimensions', width: null, height: null },
    ])
  })
})

describe('compact export panel', () => {
  it('keeps advanced controls disclosed and common controls visible', () => {
    const markup = renderToStaticMarkup(
      <ExportPanel
        ref={createRef<ExportPanelHandle>()}
        videoId="video-1"
        trackJobId="track-1"
        onPlanChange={vi.fn()}
        onJobChange={vi.fn()}
        onLibraryChange={vi.fn()}
      />,
    )

    expect(markup).toContain('aria-pressed="true"')
    expect(markup).toContain('720p')
    expect(markup).toContain('Camera smoothness')
    expect(markup).toContain('widens automatically')
    expect(markup).toContain('<summary>Advanced settings</summary>')
    expect(markup).toContain('Max acceleration')
    expect(markup).toContain('Export MP4')
    expect(markup).not.toContain('Select a player and track them first')
  })
})
