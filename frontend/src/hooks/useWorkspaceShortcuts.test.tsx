// @vitest-environment jsdom

import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { useWorkspaceShortcuts } from './useWorkspaceShortcuts'

const actions = {
  togglePlayback: vi.fn(),
  stepFrames: vi.fn(),
  primaryAction: vi.fn(),
  openLibrary: vi.fn(),
  closeSurface: vi.fn(),
}

function Harness() {
  useWorkspaceShortcuts(actions)
  return <input aria-label="Editor input" />
}

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  Object.values(actions).forEach((action) => action.mockReset())
})

afterEach(() => {
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
})

it('routes desktop editor shortcuts', async () => {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  await act(async () => root.render(<Harness />))

  window.dispatchEvent(new KeyboardEvent('keydown', { key: ' ' }))
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }))
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }))
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true }))
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))

  expect(actions.togglePlayback).toHaveBeenCalledOnce()
  expect(actions.stepFrames).toHaveBeenNthCalledWith(1, -1)
  expect(actions.stepFrames).toHaveBeenNthCalledWith(2, 1)
  expect(actions.primaryAction).toHaveBeenCalledOnce()
  expect(actions.openLibrary).toHaveBeenCalledOnce()
  expect(actions.closeSurface).toHaveBeenCalledOnce()
  await act(async () => root.unmount())
})

it('does not override typing or native control behavior', async () => {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  await act(async () => root.render(<Harness />))
  const input = container.querySelector('input')!

  for (const key of [' ', 'ArrowLeft', 'Enter', 'Escape']) {
    input.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }))
  }
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true, bubbles: true }))

  expect(actions.togglePlayback).not.toHaveBeenCalled()
  expect(actions.stepFrames).not.toHaveBeenCalled()
  expect(actions.primaryAction).not.toHaveBeenCalled()
  expect(actions.openLibrary).not.toHaveBeenCalled()
  expect(actions.closeSurface).not.toHaveBeenCalled()
  await act(async () => root.unmount())
})
