// @vitest-environment jsdom

import { act, Fragment } from 'react'
import { createRoot } from 'react-dom/client'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { OpenVideoPanel } from './OpenVideoPanel'

beforeEach(() => vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true))
afterEach(() => {
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
})

describe('OpenVideoPanel', () => {
  it('offers both a video upload and a server-path form', () => {
    const markup = renderToStaticMarkup(
      <OpenVideoPanel
        disabled={false}
        variant="drawer"
        onUpload={vi.fn()}
        onOpenPath={vi.fn()}
      />,
    )

    expect(markup).toContain('type="file"')
    expect(markup).toContain('accept="video/mp4,video/*"')
    expect(markup).toContain('Source name (optional)')
    expect(markup).toContain('maxLength="80"')
    expect(markup).toContain('Uses the filename when blank.')
    expect(markup).toContain('placeholder="examples/example.mp4"')
    expect(markup).toContain('Open server path')
    expect(markup).toContain('More options')
  })

  it('uses unique server-path field ids when two open surfaces coexist', () => {
    const markup = renderToStaticMarkup(
      <Fragment>
        <OpenVideoPanel disabled={false} variant="empty" onUpload={vi.fn()} onOpenPath={vi.fn()} />
        <OpenVideoPanel disabled={false} variant="drawer" onUpload={vi.fn()} onOpenPath={vi.fn()} />
      </Fragment>,
    )
    const ids = [...markup.matchAll(/id="([^"]*server-video-path[^"]*)"/g)].map((match) => match[1])
    expect(ids).toHaveLength(2)
    expect(new Set(ids).size).toBe(2)
  })

  it('opens a dropped video file', async () => {
    const onUpload = vi.fn().mockResolvedValue(undefined)
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    await act(async () => root.render(
      <OpenVideoPanel disabled={false} variant="empty" onUpload={onUpload} onOpenPath={vi.fn()} />,
    ))

    const file = new File(['video'], 'match.mp4', { type: 'video/mp4' })
    const drop = new Event('drop', { bubbles: true, cancelable: true })
    Object.defineProperty(drop, 'dataTransfer', { value: { files: [file] } })
    await act(async () => {
      container.querySelector('section')?.dispatchEvent(drop)
      await Promise.resolve()
    })

    expect(onUpload).toHaveBeenCalledWith(file, undefined)
    await act(async () => root.unmount())
  })

  it('passes a trimmed source name to both server-path and upload callbacks', async () => {
    const onUpload = vi.fn().mockResolvedValue(undefined)
    const onOpenPath = vi.fn().mockResolvedValue(undefined)
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    await act(async () => root.render(
      <OpenVideoPanel disabled={false} variant="empty" onUpload={onUpload} onOpenPath={onOpenPath} />,
    ))

    const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
    const nameInput = container.querySelector<HTMLInputElement>('input[aria-label="Source name (optional)"]')!
    const pathInput = container.querySelector<HTMLInputElement>('input[placeholder="examples/example.mp4"]')!
    await act(async () => {
      setValue?.call(nameInput, '  Championship Final  ')
      nameInput.dispatchEvent(new Event('input', { bubbles: true }))
      setValue?.call(pathInput, '  /videos/match.mp4  ')
      pathInput.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await act(async () => {
      container.querySelector('form')?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
      await Promise.resolve()
    })
    expect(onOpenPath).toHaveBeenCalledWith('/videos/match.mp4', 'Championship Final')

    const file = new File(['video'], 'match.mp4', { type: 'video/mp4' })
    const fileInput = container.querySelector<HTMLInputElement>('input[type="file"]')!
    Object.defineProperty(fileInput, 'files', { configurable: true, value: [file] })
    await act(async () => {
      fileInput.dispatchEvent(new Event('change', { bubbles: true }))
      await Promise.resolve()
    })
    expect(onUpload).toHaveBeenCalledWith(file, 'Championship Final')
    await act(async () => root.unmount())
  })
})
