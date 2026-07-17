import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import { OpenVideoPanel } from './OpenVideoPanel'

describe('OpenVideoPanel', () => {
  it('offers both a video upload and a server-path form', () => {
    const markup = renderToStaticMarkup(
      <OpenVideoPanel
        disabled={false}
        onUpload={vi.fn()}
        onOpenPath={vi.fn()}
      />,
    )

    expect(markup).toContain('type="file"')
    expect(markup).toContain('accept="video/mp4,video/*"')
    expect(markup).toContain('placeholder="examples/example.mp4"')
    expect(markup).toContain('Open server path')
  })
})
