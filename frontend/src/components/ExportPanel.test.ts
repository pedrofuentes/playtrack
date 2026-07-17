import { describe, expect, it } from 'vitest'

import { EXPORT_PRESETS } from './ExportPanel'

describe('EXPORT_PRESETS', () => {
  it('includes both required fixed resolutions and custom sizing', () => {
    expect(EXPORT_PRESETS).toEqual([
      { key: '1920x1080', label: '1920 × 1080', width: 1920, height: 1080 },
      { key: '1280x720', label: '1280 × 720', width: 1280, height: 720 },
      { key: 'custom', label: 'Custom', width: null, height: null },
    ])
  })
})
