import type { SourceBox } from './geometry'
import type { FrameRange } from './frameRange'

export interface VideoMetadata {
  videoId: string
  name: string
  width: number
  height: number
  fps: number
  nbFrames: number
  duration: number
}

export type LibraryVideoMetadata = Omit<VideoMetadata, 'name'>

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

export type TrackJobState = 'queued' | 'running' | 'completed' | 'failed' | 'canceled'

export interface TrackJobUpdate {
  jobId: string
  state: TrackJobState
  progress: number
  message: string
  track: TrackFrame[]
}

export interface JobWatcher {
  close(): void
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
  sourceStartFrame: number
  windows: CropWindow[]
}

export interface LibraryTrack {
  jobId: string
  name: string
  anchorFrameIdx: number
  box: SourceBox
  startFrameIdx: number
  endFrameExclusive: number
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
  metadata: LibraryVideoMetadata
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

export async function registerVideo(path: string, name?: string): Promise<VideoMetadata> {
  const trimmedName = name?.trim()
  const response = await fetch('/api/videos', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, ...(trimmedName ? { name: trimmedName } : {}) }),
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

export async function uploadVideo(file: File, name?: string): Promise<VideoMetadata> {
  const form = new FormData()
  form.append('file', file)
  const trimmedName = name?.trim()
  if (trimmedName) form.append('name', trimmedName)
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
  playerName?: string,
  range?: FrameRange,
): Promise<{ jobId: string; playerName: string }> {
  const response = await fetch('/api/track', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      videoId,
      frameIdx,
      box,
      playerName,
      ...(range ?? {}),
    }),
  })
  if (!response.ok) {
    throw new Error(await responseError(response, 'Could not start tracking'))
  }
  return (await response.json()) as { jobId: string; playerName: string }
}

export async function getTrack(jobId: string): Promise<TrackJobUpdate> {
  const response = await fetch(`/api/track/${encodeURIComponent(jobId)}`)
  if (!response.ok) {
    throw new Error(await responseError(response, 'Could not fetch track'))
  }
  return (await response.json()) as TrackJobUpdate
}

export async function getJob(jobId: string): Promise<TrackJobUpdate> {
  const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`)
  if (!response.ok) {
    throw new Error(await responseError(response, 'Could not fetch job'))
  }
  return (await response.json()) as TrackJobUpdate
}

export async function cancelJob(jobId: string): Promise<TrackJobUpdate> {
  const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: 'POST',
  })
  if (!response.ok) {
    throw new Error(await responseError(response, 'Could not cancel job'))
  }
  return (await response.json()) as TrackJobUpdate
}

export function trackJobWebSocketUrl(
  jobId: string,
  pageLocation: WebSocketLocation = window.location,
): string {
  const protocol = pageLocation.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${pageLocation.host}/ws/jobs/${encodeURIComponent(jobId)}?protocol=delta-v1`
}

export function watchTrackJob(
  jobId: string,
  onUpdate: (update: TrackJobUpdate) => void,
  onError: (message: string) => void,
): JobWatcher {
  const maximumReconnects = 3
  let socket: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof globalThis.setTimeout> | null = null
  let reconnectAttempts = 0
  let generation = 0
  let disposed = false
  let latest: TrackJobUpdate | null = null
  let latestVersion = -1

  const isTerminal = (update: TrackJobUpdate) => (
    update.state === 'completed' || update.state === 'failed' || update.state === 'canceled'
  )

  const stopSocket = () => {
    const active = socket
    socket = null
    if (active) {
      active.onopen = null
      active.onmessage = null
      active.onerror = null
      active.onclose = null
      active.close()
    }
  }

  const emit = (update: TrackJobUpdate) => {
    latest = update
    onUpdate(update)
    if (isTerminal(update)) {
      disposed = true
      if (reconnectTimer !== null) globalThis.clearTimeout(reconnectTimer)
      reconnectTimer = null
      stopSocket()
    }
  }

  const scheduleReconnect = () => {
    if (disposed) return
    if (reconnectAttempts >= maximumReconnects) {
      disposed = true
      onError('Lost the tracking progress connection')
      return
    }
    reconnectAttempts += 1
    reconnectTimer = globalThis.setTimeout(
      connect,
      250 * 2 ** (reconnectAttempts - 1),
    )
  }

  const recover = async () => {
    try {
      const recovered = await getJob(jobId)
      if (disposed) return
      emit(recovered)
      if (!isTerminal(recovered)) scheduleReconnect()
    } catch {
      if (!disposed) scheduleReconnect()
    }
  }

  const applyMessage = (raw: unknown): boolean => {
    if (!raw || typeof raw !== 'object') return false
    const message = raw as Record<string, unknown>
    if (message.type === 'heartbeat') return true
    if (message.type === 'snapshot') {
      if (!isTrackJobUpdate(message) || !Number.isInteger(message.version)) return false
      latestVersion = Number(message.version)
      emit(toTrackJobUpdate(message))
      return true
    }
    if (message.type === 'delta') {
      if (
        latest === null
        || !Number.isInteger(message.version)
        || Number(message.version) !== latestVersion + 1
        || !isJobState(message.state)
        || typeof message.progress !== 'number'
        || typeof message.message !== 'string'
        || !Array.isArray(message.track)
        || !Array.isArray(message.removedFrameIdxs)
      ) return false
      const frames = new Map(latest.track.map((frame) => [frame.frameIdx, frame]))
      for (const frameIdx of message.removedFrameIdxs) {
        if (typeof frameIdx !== 'number') return false
        frames.delete(frameIdx)
      }
      for (const frame of message.track) {
        if (!isTrackFrame(frame)) return false
        frames.set(frame.frameIdx, frame)
      }
      latestVersion = Number(message.version)
      emit({
        jobId,
        state: message.state,
        progress: message.progress,
        message: message.message,
        track: [...frames.values()].sort((left, right) => left.frameIdx - right.frameIdx),
      })
      return true
    }
    if (isTrackJobUpdate(message)) {
      emit(toTrackJobUpdate(message))
      return true
    }
    return false
  }

  function connect() {
    if (disposed) return
    reconnectTimer = null
    const currentGeneration = ++generation
    let handledDisconnect = false
    try {
      const active = new WebSocket(trackJobWebSocketUrl(jobId))
      socket = active
      const disconnect = () => {
        if (disposed || handledDisconnect || currentGeneration !== generation) return
        handledDisconnect = true
        if (socket === active) socket = null
        void recover()
      }
      active.onmessage = (event) => {
        if (disposed || currentGeneration !== generation) return
        try {
          if (!applyMessage(JSON.parse(String(event.data)))) {
            active.close()
            disconnect()
            return
          }
          reconnectAttempts = 0
        } catch {
          active.close()
          disconnect()
        }
      }
      active.onerror = () => {
        active.close()
        disconnect()
      }
      active.onclose = disconnect
    } catch {
      void recover()
    }
  }

  connect()
  return {
    close() {
      if (disposed) return
      disposed = true
      generation += 1
      if (reconnectTimer !== null) globalThis.clearTimeout(reconnectTimer)
      reconnectTimer = null
      stopSocket()
    },
  }
}

function isJobState(value: unknown): value is TrackJobState {
  return value === 'queued' || value === 'running' || value === 'completed'
    || value === 'failed' || value === 'canceled'
}

function isTrackFrame(value: unknown): value is TrackFrame {
  if (!value || typeof value !== 'object') return false
  const frame = value as Partial<TrackFrame>
  return Number.isInteger(frame.frameIdx) && typeof frame.lost === 'boolean'
}

function isTrackJobUpdate(value: Record<string, unknown>): boolean {
  return typeof value.jobId === 'string' && isJobState(value.state)
    && typeof value.progress === 'number' && typeof value.message === 'string'
    && Array.isArray(value.track) && value.track.every(isTrackFrame)
}

function toTrackJobUpdate(value: Record<string, unknown>): TrackJobUpdate {
  return {
    jobId: String(value.jobId),
    state: value.state as TrackJobState,
    progress: Number(value.progress),
    message: String(value.message),
    track: value.track as TrackFrame[],
  }
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

export async function renameLibraryPlayer(
  jobId: string,
  name: string,
): Promise<{ jobId: string; name: string }> {
  const response = await fetch(`/api/library/tracks/${encodeURIComponent(jobId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
  if (!response.ok) throw new Error(await responseError(response, 'Could not rename player'))
  return (await response.json()) as { jobId: string; name: string }
}

export async function renameLibrarySource(
  videoId: string,
  name: string,
): Promise<{ videoId: string; name: string }> {
  const response = await fetch(`/api/library/videos/${encodeURIComponent(videoId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
  if (!response.ok) throw new Error(await responseError(response, 'Could not rename source'))
  return (await response.json()) as { videoId: string; name: string }
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
