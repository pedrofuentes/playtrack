import { describe, expect, it } from 'vitest'

import type { ClickSelection, TrackJobUpdate } from './api'
import { isJobActive, workspaceStage } from './workflow'

const selection: ClickSelection = {
  box: [1, 2, 3, 4],
  maskPng: '',
  score: 0.9,
}

function job(state: TrackJobUpdate['state']): TrackJobUpdate {
  return {
    jobId: 'track-1',
    state,
    progress: state === 'completed' ? 1 : 0.5,
    message: state,
    track: [],
  }
}

describe('workspaceStage', () => {
  it('advances through select, track, review, and export', () => {
    expect(workspaceStage(null, null, false)).toBe('select')
    expect(workspaceStage(selection, job('running'), false)).toBe('track')
    expect(workspaceStage(null, job('completed'), false)).toBe('review')
    expect(workspaceStage(selection, job('completed'), true)).toBe('export')
  })

  it('keeps selection and start failures in the select stage', () => {
    expect(workspaceStage(selection, null, false)).toBe('select')
    expect(workspaceStage(selection, job('failed'), false)).toBe('track')
  })
})

describe('isJobActive', () => {
  it('recognizes queued and running jobs only', () => {
    expect(isJobActive(job('queued'))).toBe(true)
    expect(isJobActive(job('running'))).toBe(true)
    expect(isJobActive(job('completed'))).toBe(false)
    expect(isJobActive(job('failed'))).toBe(false)
    expect(isJobActive(null)).toBe(false)
  })
})
