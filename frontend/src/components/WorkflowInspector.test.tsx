import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import type { ClickSelection, TrackJobUpdate, VideoMetadata } from '../api'
import { WorkflowInspector } from './WorkflowInspector'

const video: VideoMetadata = {
  videoId: 'video-1', name: 'Championship Final', width: 4096, height: 1024, fps: 30, nbFrames: 930, duration: 31,
}
const selection: ClickSelection = { box: [1, 2, 3, 4], maskPng: '', score: 0.92 }

const common = {
  video,
  currentFrame: 368,
  selection: null,
  selectionKind: 'click' as const,
  selectionLoading: false,
  selectionError: null,
  candidates: [],
  playerName: '',
  textSelectionEnabled: false,
  trackJob: null,
  trackMessage: null,
  trackError: null,
  trackStartedAt: null,
  health: null,
  onTextSelect: vi.fn(),
  onPlayerNameChange: vi.fn(),
  onTrack: vi.fn(),
  onRetryTrack: vi.fn(),
  onResetSelection: vi.fn(),
  onBeginFraming: vi.fn(),
  onSeek: vi.fn(),
  exportPanel: <div>Export controls</div>,
}

function job(state: TrackJobUpdate['state'], progress = 0.64): TrackJobUpdate {
  return { jobId: 'track-1', state, progress, message: state, track: [] }
}

describe('WorkflowInspector', () => {
  it('shows click-first selection and exposes description only when enabled', () => {
    const clickOnly = renderToStaticMarkup(<WorkflowInspector {...common} stage="select" />)
    expect(clickOnly).toContain('Click a player')
    expect(clickOnly).not.toContain('Describe')

    const selected = renderToStaticMarkup(
      <WorkflowInspector
        {...common}
        stage="select"
        selection={selection}
        textSelectionEnabled
      />,
    )
    expect(selected).toContain('Describe')
    expect(selected).toContain('92% confidence')
    expect(selected).toContain('Name this player')
    expect(selected).toContain('maxLength="80"')
    expect(selected).toContain('Track player')
  })

  it('shows determinate tracking progress and local retry', () => {
    const running = renderToStaticMarkup(
      <WorkflowInspector {...common} stage="track" selection={selection} trackJob={job('running')} />,
    )
    expect(running).toContain('595 of 930 frames')
    expect(running).toContain('64%')
    expect(running).not.toContain('Set framing')

    const failed = renderToStaticMarkup(
      <WorkflowInspector
        {...common}
        stage="track"
        selection={selection}
        trackJob={job('failed')}
        trackError="Out of memory"
      />,
    )
    expect(failed).toContain('Out of memory')
    expect(failed).toContain('Retry tracking')
  })

  it('summarizes review ranges and renders export alone in export state', () => {
    const health = {
      coveredCount: 906,
      lostCount: 24,
      coverage: 906 / 930,
      lostRanges: [{ startFrame: 400, endFrame: 423, frameCount: 24 }],
    }
    const review = renderToStaticMarkup(
      <WorkflowInspector
        {...common}
        stage="review"
        selection={selection}
        trackJob={job('completed', 1)}
        health={health}
      />,
    )
    expect(review).toContain('97%')
    expect(review).toContain('24 lost frames')
    expect(review).toContain('Frames 400–423')
    expect(review).toContain('Set framing')

    const exportMarkup = renderToStaticMarkup(
      <WorkflowInspector {...common} stage="export" selection={selection} trackJob={job('completed', 1)} />,
    )
    expect(exportMarkup).toContain('Export controls')
    expect(exportMarkup).not.toContain('Click a player')
    expect(exportMarkup).not.toContain('Set framing')
  })
})
