// @vitest-environment jsdom

import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { WorkspaceShell } from './WorkspaceShell'

const commonProps = {
  videoName: 'match.mp4',
  videoMeta: '4096 × 1024 · 31 sec',
  saved: true,
  openingDisabled: false,
  onOpenUpload: vi.fn(),
  topAction: <button type="button">Export</button>,
  canvas: <div>Canvas</div>,
  inspector: <div>Inspector</div>,
  timeline: <div>Timeline</div>,
  library: <div>Library contents</div>,
  jobs: <div>Job contents</div>,
  settings: <div>Settings contents</div>,
}

beforeEach(() => vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true))
afterEach(() => {
  document.body.innerHTML = ''
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it('provides stable top bar, editor regions, and labeled activity navigation', () => {
  const markup = renderToStaticMarkup(
    <WorkspaceShell
      {...commonProps}
      surface="editor"
      onSurfaceChange={vi.fn()}
    />,
  )

  expect(markup).toContain('match.mp4')
  expect(markup).toContain('4096 × 1024 · 31 sec')
  expect(markup).toContain('aria-label="Editor tools"')
  expect(markup).toContain('aria-label="PlayTrack home"')
  expect(markup).toContain('src="/brand/playtrack-mark.svg"')
  expect(markup).not.toContain('aria-label="FindMe"')
  expect(markup).toContain('Editor')
  expect(markup).toContain('Library')
  expect(markup).toContain('Jobs')
  expect(markup).toContain('Settings')
  expect(markup).toContain('Canvas')
  expect(markup).toContain('Inspector')
  expect(markup).toContain('Timeline')
  expect(markup).toContain('Ctrl/⌘ K')
  expect(markup).not.toContain('Library contents')
})

it('shows a non-modal drawer and closes it with Escape', async () => {
  const onSurfaceChange = vi.fn()
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  await act(async () => root.render(
    <WorkspaceShell
      {...commonProps}
      surface="library"
      onSurfaceChange={onSurfaceChange}
    />,
  ))

  expect(container.querySelector('[role="dialog"]')?.textContent).toContain('Library contents')
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  expect(onSurfaceChange).toHaveBeenCalledWith('editor')
  await act(async () => root.unmount())
})
