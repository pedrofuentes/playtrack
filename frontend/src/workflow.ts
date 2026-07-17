import type { ClickSelection, TrackJobUpdate } from './api'

export type WorkspaceStage = 'select' | 'track' | 'review' | 'export'

export function workspaceStage(
  _selection: ClickSelection | null,
  trackJob: TrackJobUpdate | null,
  framing: boolean,
): WorkspaceStage {
  if (trackJob?.state === 'completed') return framing ? 'export' : 'review'
  if (trackJob) return 'track'
  return 'select'
}

export function isJobActive(job: TrackJobUpdate | null): boolean {
  return job?.state === 'queued' || job?.state === 'running'
}
