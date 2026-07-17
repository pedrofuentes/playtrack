import { createElement } from 'react'
import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import { EXPORT_PRESETS, ExportPanel } from './ExportPanel'

describe('EXPORT_PRESETS', () => {
  it('includes both required fixed resolutions and custom sizing', () => {
    expect(EXPORT_PRESETS).toEqual([
      { key: '1920x1080', label: '1920 × 1080', width: 1920, height: 1080 },
      { key: '1280x720', label: '1280 × 720', width: 1280, height: 720 },
      { key: 'custom', label: 'Custom', width: null, height: null },
    ])
  })
})

describe('disabled export panel', () => {
  it('keeps export visible while explaining how to unlock it', () => {
    const markup = renderToStaticMarkup(
      createElement(ExportPanel, {
        videoId: '',
        trackJobId: '',
        disabled: true,
        onPlanChange: () => {},
      }),
    )

    expect(markup).toContain('<fieldset disabled=""')
    expect(markup).toContain(
      'Select a player and track them first — then export a video that follows them.',
    )
  })
})
