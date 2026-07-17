// @vitest-environment jsdom

import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { SettingsPanel } from './SettingsPanel'

beforeEach(() => vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true))
afterEach(() => {
  document.body.innerHTML = ''
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it('disables frame-cache clearing during active jobs', async () => {
  const onClearFrameCaches = vi.fn().mockResolvedValue(undefined)
  const confirm = vi.spyOn(window, 'confirm')
  const container = document.createElement('div')
  const root = createRoot(container)

  await act(async () => root.render(
    <SettingsPanel cacheBytes={1024} disabled onClearFrameCaches={onClearFrameCaches} />,
  ))
  const clear = [...container.querySelectorAll('button')]
    .find((item) => item.textContent === 'Clear frame cache')!
  expect(clear.disabled).toBe(true)
  await act(async () => clear.click())
  expect(confirm).not.toHaveBeenCalled()
  expect(onClearFrameCaches).not.toHaveBeenCalled()
  await act(async () => root.unmount())
})
