import { describe, expect, it } from 'vitest'

import { currentWorkflowStep, libraryVideoName } from './App'

describe('currentWorkflowStep', () => {
  it('advances from selection to tracking to export', () => {
    expect(currentWorkflowStep(null, null)).toBe(1)
    expect(
      currentWorkflowStep(
        { box: [1, 2, 3, 4], maskPng: '', score: 0.9 },
        null,
      ),
    ).toBe(2)
    expect(
      currentWorkflowStep(null, {
        jobId: 'track-1',
        state: 'completed',
        progress: 1,
        message: 'done',
        track: [],
      }),
    ).toBe(3)
  })
})

it('uses the library display name when opening a saved upload', () => {
  expect(libraryVideoName({ name: 'Championship Final.mp4' } as never)).toBe(
    'Championship Final.mp4',
  )
})
