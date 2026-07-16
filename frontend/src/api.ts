import type { SourceBox } from './geometry'

export interface VideoMetadata {
  videoId: string
  width: number
  height: number
  fps: number
  nbFrames: number
  duration: number
}

export interface ClickSelection {
  box: SourceBox
  maskPng: string
  score: number
}

export interface TrackFrame {
  frameIdx: number
  box: SourceBox | null
  center: readonly [number, number] | null
  lost: boolean
}

export type TrackJobState = 'queued' | 'running' | 'completed' | 'failed'

export interface TrackJobUpdate {
  jobId: string
  state: TrackJobState
  progress: number
  message: string
  track: TrackFrame[]
}

interface WebSocketLocation {
  protocol: string
  host: string
}

export async function registerVideo(path: string): Promise<VideoMetadata> {
  const response = await fetch('/api/videos', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  })
  if (!response.ok) {
    let message = `Could not open video (${response.status})`
    try {
      const payload = (await response.json()) as { detail?: string }
      if (payload.detail) message = payload.detail
    } catch {
      // Keep the status-based message if the response is not JSON.
    }
    throw new Error(message)
  }
  return (await response.json()) as VideoMetadata
}

export function videoFileUrl(videoId: string): string {
  return `/api/videos/${encodeURIComponent(videoId)}/file`
}

export async function selectByClick(
  videoId: string,
  frameIdx: number,
  x: number,
  y: number,
  signal?: AbortSignal,
): Promise<ClickSelection> {
  const response = await fetch('/api/select/click', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ videoId, frameIdx, x, y }),
    signal,
  })
  if (!response.ok) {
    let message = `Could not select player (${response.status})`
    try {
      const payload = (await response.json()) as { detail?: string }
      if (payload.detail) message = payload.detail
    } catch {
      // Keep the status-based message if the response is not JSON.
    }
    throw new Error(message)
  }
  return (await response.json()) as ClickSelection
}

export async function startTracking(
  videoId: string,
  frameIdx: number,
  box: SourceBox,
): Promise<{ jobId: string }> {
  const response = await fetch('/api/track', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ videoId, frameIdx, box }),
  })
  if (!response.ok) {
    throw new Error(await responseError(response, 'Could not start tracking'))
  }
  return (await response.json()) as { jobId: string }
}

export async function getTrack(jobId: string): Promise<TrackJobUpdate> {
  const response = await fetch(`/api/track/${encodeURIComponent(jobId)}`)
  if (!response.ok) {
    throw new Error(await responseError(response, 'Could not fetch track'))
  }
  return (await response.json()) as TrackJobUpdate
}

export function trackJobWebSocketUrl(
  jobId: string,
  pageLocation: WebSocketLocation = window.location,
): string {
  const protocol = pageLocation.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${pageLocation.host}/ws/jobs/${encodeURIComponent(jobId)}`
}

export function watchTrackJob(
  jobId: string,
  onUpdate: (update: TrackJobUpdate) => void,
  onError: (message: string) => void,
): WebSocket {
  const socket = new WebSocket(trackJobWebSocketUrl(jobId))
  socket.onmessage = (event) => {
    onUpdate(JSON.parse(String(event.data)) as TrackJobUpdate)
  }
  socket.onerror = () => onError('Lost the tracking progress connection')
  return socket
}

async function responseError(response: Response, fallback: string): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string }
    if (payload.detail) return payload.detail
  } catch {
    // Use the status-based fallback for non-JSON responses.
  }
  return `${fallback} (${response.status})`
}
