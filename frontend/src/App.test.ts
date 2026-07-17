import { describe, expect, it } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import App, { libraryVideoName } from './App'
import { workspaceStage } from './workflow'

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
