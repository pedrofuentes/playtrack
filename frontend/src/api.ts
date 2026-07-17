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

export interface LocateCandidate {
  box: SourceBox
  score: number
}

export interface FeatureFlags {
  textSelection: {
    enabled: boolean
    reason: string
  }
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

export interface SmoothingSettings {
  responsiveness: number
  maxAccelPxPerFrame2: number
}

export interface ExportSettings {
  outWidth: number
  outHeight: number
  zoom: number
  smoothing: SmoothingSettings
}

export interface CropWindow {
  frameIdx: number
  x: number
  y: number
  w: number
  h: number
}

export interface CropPlanResponse {
  videoId: string
  trackJobId: string
  windows: CropWindow[]
}

export interface LibraryTrack {
  jobId: string
  anchorFrameIdx: number
  box: SourceBox
  frameCount: number
  lostCount: number
  createdAt: string
}

export interface LibraryExport {
  exportId: string
  videoId: string
  trackJobId: string
  params: { outWidth?: number; outHeight?: number; [key: string]: unknown }
  path: string
  size: number
  createdAt: string
  sourceExists: boolean
}

export interface LibraryVideo {
  videoId: string
  name: string
  sourceKind: 'path' | 'upload'
  path: string
  metadata: VideoMetadata
  size: number
  openedAt: string | null
  sourceExists: boolean
  tracks: LibraryTrack[]
  exports: LibraryExport[]
}

export interface LibraryResponse {
  videos: LibraryVideo[]
  cacheBytes: number
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

export async function uploadVideo(file: File): Promise<VideoMetadata> {
  const form = new FormData()
  form.append('file', file)
  const response = await fetch('/api/videos', {
    method: 'POST',
    body: form,
  })
  if (!response.ok) {
    throw new Error(await responseError(response, 'Could not upload video'))
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

export async function getFeatures(): Promise<FeatureFlags> {
  const response = await fetch('/api/features')
  if (!response.ok) {
    throw new Error(await responseError(response, 'Could not read feature flags'))
  }
  return (await response.json()) as FeatureFlags
}

export async function selectByText(
  videoId: string,
  frameIdx: number,
  prompt: string,
  signal?: AbortSignal,
): Promise<LocateCandidate[]> {
  const response = await fetch('/api/select/text', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ videoId, frameIdx, prompt }),
    signal,
  })
  if (!response.ok) {
    throw new Error(await responseError(response, 'Could not ground text prompt'))
  }
  const payload = (await response.json()) as { candidates: LocateCandidate[] }
  return payload.candidates
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

export async function fetchCropPlan(
  videoId: string,
  trackJobId: string,
  settings: ExportSettings,
  signal?: AbortSignal,
): Promise<CropPlanResponse> {
  const query = new URLSearchParams({
    videoId,
    trackJobId,
    outWidth: String(settings.outWidth),
    outHeight: String(settings.outHeight),
    zoom: String(settings.zoom),
    responsiveness: String(settings.smoothing.responsiveness),
    maxAccelPxPerFrame2: String(settings.smoothing.maxAccelPxPerFrame2),
  })
  const response = await fetch(`/api/export/plan?${query}`, { signal })
  if (!response.ok) {
    throw new Error(await responseError(response, 'Could not preview crop'))
  }
  return (await response.json()) as CropPlanResponse
}

export async function startExport(
  videoId: string,
  trackJobId: string,
  settings: ExportSettings,
): Promise<{ jobId: string }> {
  const response = await fetch('/api/export', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ videoId, trackJobId, ...settings }),
  })
  if (!response.ok) {
    throw new Error(await responseError(response, 'Could not start export'))
  }
  return (await response.json()) as { jobId: string }
}

export function exportDownloadUrl(jobId: string): string {
  return `/api/exports/${encodeURIComponent(jobId)}.mp4`
}

export async function getLibrary(): Promise<LibraryResponse> {
  const response = await fetch('/api/library')
  if (!response.ok) throw new Error(await responseError(response, 'Could not load library'))
  return (await response.json()) as LibraryResponse
}

export async function deleteLibraryVideo(videoId: string): Promise<void> {
  await deleteLibraryItem(`/api/library/videos/${encodeURIComponent(videoId)}`)
}

export async function deleteLibraryTrack(jobId: string): Promise<void> {
  await deleteLibraryItem(`/api/library/tracks/${encodeURIComponent(jobId)}`)
}

export async function deleteLibraryExport(exportId: string): Promise<void> {
  await deleteLibraryItem(`/api/library/exports/${encodeURIComponent(exportId)}`)
}

export async function clearFrameCaches(): Promise<{ bytesFreed: number }> {
  const response = await fetch('/api/library/maintenance/clear-caches', { method: 'POST' })
  if (!response.ok) throw new Error(await responseError(response, 'Could not clear caches'))
  return (await response.json()) as { bytesFreed: number }
}

async function deleteLibraryItem(url: string): Promise<void> {
  const response = await fetch(url, { method: 'DELETE' })
  if (!response.ok) throw new Error(await responseError(response, 'Could not delete library item'))
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
