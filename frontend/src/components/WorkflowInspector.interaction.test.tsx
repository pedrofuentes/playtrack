// @vitest-environment jsdom

import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { WorkflowInspector } from './WorkflowInspector'

beforeEach(() => vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true))
afterEach(() => {
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
})

it('switches between click and description selection methods', async () => {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  await act(async () => root.render(
    <WorkflowInspector
      stage="select"
      video={{ videoId: 'video-1', name: 'Championship Final', width: 4096, height: 1024, fps: 30, nbFrames: 930, duration: 31 }}
      currentFrame={10}
      selection={null}
      selectionKind="click"
      selectionLoading={false}
      selectionError={null}
      candidates={[]}
      playerName=""
      textSelectionEnabled
      trackJob={null}
      trackMessage={null}
      trackError={null}
      trackStartedAt={null}
      health={null}
      onTextSelect={vi.fn()}
      onPlayerNameChange={vi.fn()}
      onTrack={vi.fn()}
      onRetryTrack={vi.fn()}
      onResetSelection={vi.fn()}
      onBeginFraming={vi.fn()}
      onSeek={vi.fn()}
      exportPanel={null}
    />,
  ))

  expect(container.querySelector('#player-description')).toBeNull()
  await act(async () => container.querySelector<HTMLButtonElement>('button[data-method="describe"]')?.click())
  expect(container.querySelector('#player-description')).not.toBeNull()
  await act(async () => container.querySelector<HTMLButtonElement>('button[data-method="click"]')?.click())
  expect(container.querySelector('#player-description')).toBeNull()
  await act(async () => root.unmount())
})
