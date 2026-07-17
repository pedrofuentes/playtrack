import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  clearFrameCaches,
  type ClickSelection,
  type CropWindow,
  type FeatureFlags,
  getFeatures,
  getLibrary,
  getTrack,
  type LibraryResponse,
  type LibraryVideo,
  type LocateCandidate,
  registerVideo,
  selectByClick,
  selectByText,
  startTracking,
  type TrackJobUpdate,
  type VideoMetadata,
  watchTrackJob,
  uploadVideo,
} from '../api'
import type { Point } from '../geometry'
import { isJobActive, type WorkspaceStage, workspaceStage } from '../workflow'

const EXAMPLE_PATH = 'examples/example.mp4'

export interface WorkspaceController {
  video: VideoMetadata | null
  videoName: string | null
  currentFrame: number
  selection: ClickSelection | null
  selectionKind: 'click' | 'text'
  selectionLoading: boolean
  selectionError: string | null
  candidates: LocateCandidate[]
  features: FeatureFlags
  library: LibraryResponse
  trackJob: TrackJobUpdate | null
  trackMessage: string | null
  trackError: string | null
  trackStarting: boolean
  trackStartedAt: number | null
  cropWindows: CropWindow[]
  loading: boolean
  loadingLabel: string
  openError: string | null
  framing: boolean
  exportJob: TrackJobUpdate | null
  stage: WorkspaceStage
  videoSwitchLocked: boolean
  openUpload(file: File): Promise<void>
  openPath(path: string): Promise<void>
  openLibraryVideo(video: LibraryVideo): Promise<void>
  reExportLibraryTrack(video: LibraryVideo, jobId: string): Promise<void>
  refreshLibrary(): void
  selectAt(point: Point, frameIdx: number): void
  selectByDescription(prompt: string): void
  confirmCandidate(candidate: LocateCandidate, frameIdx: number): void
  setCurrentFrame(frameIdx: number): void
  startTrack(): Promise<void>
  retryTrack(): Promise<void>
  beginFraming(): void
  setCropWindows(windows: CropWindow[]): void
  setExportJob(job: TrackJobUpdate | null): void
  resetSelection(): void
  clearCaches(): Promise<void>
}

export function useWorkspace(): WorkspaceController {
  const [video, setVideo] = useState<VideoMetadata | null>(null)
  const [videoName, setVideoName] = useState<string | null>(null)
  const [currentFrame, setCurrentFrameState] = useState(0)
  const [anchorFrame, setAnchorFrame] = useState<number | null>(null)
  const [selection, setSelection] = useState<ClickSelection | null>(null)
  const [selectionKind, setSelectionKind] = useState<'click' | 'text'>('click')
  const [selectionLoading, setSelectionLoading] = useState(false)
  const [selectionError, setSelectionError] = useState<string | null>(null)
  const [candidates, setCandidates] = useState<LocateCandidate[]>([])
  const [candidateFrame, setCandidateFrame] = useState<number | null>(null)
  const [features, setFeatures] = useState<FeatureFlags>({
    textSelection: { enabled: false, reason: '' },
  })
  const [library, setLibrary] = useState<LibraryResponse>({ videos: [], cacheBytes: 0 })
  const [trackJob, setTrackJob] = useState<TrackJobUpdate | null>(null)
  const [trackMessage, setTrackMessage] = useState<string | null>(null)
  const [trackError, setTrackError] = useState<string | null>(null)
  const [trackStarting, setTrackStarting] = useState(false)
  const [trackStartedAt, setTrackStartedAt] = useState<number | null>(null)
  const [cropWindows, setCropWindowsState] = useState<CropWindow[]>([])
  const [loading, setLoading] = useState(true)
  const [loadingLabel, setLoadingLabel] = useState(`Opening ${EXAMPLE_PATH}…`)
  const [openError, setOpenError] = useState<string | null>(null)
  const [framing, setFraming] = useState(false)
  const [exportJob, setExportJobState] = useState<TrackJobUpdate | null>(null)
  const selectionRequest = useRef<AbortController | null>(null)
  const trackSocket = useRef<WebSocket | null>(null)

  const stage = workspaceStage(selection, trackJob, framing)
  const videoSwitchLocked = trackStarting || isJobActive(trackJob) || isJobActive(exportJob)
  const videoSwitchLockedRef = useRef(videoSwitchLocked)
  videoSwitchLockedRef.current = videoSwitchLocked

  const clearDownstreamState = useCallback(() => {
    trackSocket.current?.close()
    trackSocket.current = null
    setTrackJob(null)
    setTrackMessage(null)
    setTrackError(null)
    setTrackStarting(false)
    setTrackStartedAt(null)
    setCropWindowsState([])
    setFraming(false)
    setExportJobState(null)
  }, [])

  const openVideo = useCallback(async (
    register: () => Promise<VideoMetadata>,
    filename: string,
    activity: string,
  ) => {
    if (videoSwitchLockedRef.current) return
    selectionRequest.current?.abort()
    selectionRequest.current = null
    clearDownstreamState()
    setLoading(true)
    setLoadingLabel(activity)
    setOpenError(null)
    setCurrentFrameState(0)
    setAnchorFrame(null)
    setSelection(null)
    setSelectionKind('click')
    setSelectionLoading(false)
    setSelectionError(null)
    setCandidates([])
    setCandidateFrame(null)
    try {
      setVideo(await register())
      setVideoName(filename)
    } catch (reason) {
      setVideo(null)
      setVideoName(null)
      setOpenError(reason instanceof Error ? reason.message : `Could not open ${filename}`)
    } finally {
      setLoading(false)
    }
  }, [clearDownstreamState])

  const refreshLibrary = useCallback(() => {
    void getLibrary().then(setLibrary).catch(() => {})
  }, [])

  const openPath = useCallback((path: string) => openVideo(
    () => registerVideo(path),
    filenameFromPath(path),
    `Opening ${path}…`,
  ), [openVideo])

  const openUpload = useCallback((file: File) => openVideo(
    () => uploadVideo(file),
    file.name,
    `Uploading ${file.name}…`,
  ), [openVideo])

  const openLibraryVideo = useCallback((saved: LibraryVideo) => openVideo(
    () => Promise.resolve(saved.metadata),
    saved.name,
    `Opening ${saved.name}…`,
  ), [openVideo])

  const reExportLibraryTrack = useCallback(async (saved: LibraryVideo, jobId: string) => {
    if (videoSwitchLocked) return
    await openLibraryVideo(saved)
    try {
      const restored = await getTrack(jobId)
      setTrackJob(restored)
      setTrackMessage(restored.message)
      setTrackError(restored.state === 'failed' ? restored.message : null)
      setTrackStartedAt(null)
      setFraming(restored.state === 'completed')
    } catch (reason) {
      setTrackError(reason instanceof Error ? reason.message : 'Could not restore saved track')
    }
  }, [openLibraryVideo, videoSwitchLocked])

  useEffect(() => {
    void openPath(EXAMPLE_PATH)
    refreshLibrary()
    void getFeatures()
      .then(setFeatures)
      .catch(() => setFeatures({
        textSelection: { enabled: false, reason: 'Feature status is unavailable' },
      }))
  }, [openPath, refreshLibrary])

  useEffect(() => () => {
    selectionRequest.current?.abort()
    trackSocket.current?.close()
  }, [])

  const prepareSelection = useCallback((frameIdx: number, kind: 'click' | 'text') => {
    trackSocket.current?.close()
    trackSocket.current = null
    setAnchorFrame(frameIdx)
    setSelection(null)
    setSelectionKind(kind)
    setCandidates([])
    setCandidateFrame(null)
    setSelectionError(null)
    clearDownstreamState()
    setSelectionLoading(true)
  }, [clearDownstreamState])

  const selectAt = useCallback((point: Point, frameIdx: number) => {
    if (!video) return
    selectionRequest.current?.abort()
    const controller = new AbortController()
    selectionRequest.current = controller
    prepareSelection(frameIdx, 'click')
    void selectByClick(video.videoId, frameIdx, point.x, point.y, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setSelection(result)
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return
        setSelectionError(reason instanceof Error ? reason.message : 'Could not select player')
      })
      .finally(() => {
        if (selectionRequest.current === controller) {
          selectionRequest.current = null
          setSelectionLoading(false)
        }
      })
  }, [prepareSelection, video])

  const selectByDescription = useCallback((rawPrompt: string) => {
    const prompt = rawPrompt.trim()
    if (!video || !prompt) return
    selectionRequest.current?.abort()
    const controller = new AbortController()
    selectionRequest.current = controller
    prepareSelection(currentFrame, 'text')
    void selectByText(video.videoId, currentFrame, prompt, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return
        setCandidates(result)
        setCandidateFrame(currentFrame)
        if (result.length === 0) setSelectionError('No players matched that prompt')
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return
        setSelectionError(reason instanceof Error ? reason.message : 'Could not ground text prompt')
      })
      .finally(() => {
        if (selectionRequest.current === controller) {
          selectionRequest.current = null
          setSelectionLoading(false)
        }
      })
  }, [currentFrame, prepareSelection, video])

  const confirmCandidate = useCallback((candidate: LocateCandidate, frameIdx: number) => {
    setSelection({ box: candidate.box, score: candidate.score, maskPng: '' })
    setSelectionKind('text')
    setAnchorFrame(frameIdx)
    setCandidates([])
    setCandidateFrame(null)
    setSelectionError(null)
  }, [])

  const setCurrentFrame = useCallback((frameIdx: number) => {
    setCurrentFrameState(frameIdx)
    if (candidateFrame !== null && frameIdx !== candidateFrame) {
      setCandidates([])
      setCandidateFrame(null)
    }
  }, [candidateFrame])

  const startTrack = useCallback(async () => {
    if (!video || !selection || anchorFrame === null) return
    trackSocket.current?.close()
    trackSocket.current = null
    setTrackStarting(true)
    setTrackStartedAt(Date.now())
    setTrackError(null)
    setTrackMessage('Starting SAM 2 video propagation…')
    setTrackJob(null)
    setCropWindowsState([])
    setFraming(false)
    setExportJobState(null)
    try {
      const { jobId } = await startTracking(video.videoId, anchorFrame, selection.box)
      setTrackJob({
        jobId,
        state: 'queued',
        progress: 0,
        message: 'Tracking queued…',
        track: [],
      })
      const socket = watchTrackJob(
        jobId,
        (update) => {
          setTrackJob(update)
          setTrackMessage(update.message)
          if (update.state === 'failed') setTrackError(update.message)
          if (update.state === 'completed' || update.state === 'failed') {
            if (trackSocket.current === socket) trackSocket.current = null
            socket.close()
            refreshLibrary()
          }
        },
        (message) => {
          setTrackError(message)
          setTrackMessage(null)
          setTrackJob((current) => current ? { ...current, state: 'failed', message } : null)
        },
      )
      trackSocket.current = socket
    } catch (reason) {
      setTrackError(reason instanceof Error ? reason.message : 'Could not start tracking')
      setTrackMessage(null)
    } finally {
      setTrackStarting(false)
    }
  }, [anchorFrame, refreshLibrary, selection, video])

  const resetSelection = useCallback(() => {
    selectionRequest.current?.abort()
    selectionRequest.current = null
    setAnchorFrame(null)
    setSelection(null)
    setSelectionKind('click')
    setSelectionLoading(false)
    setSelectionError(null)
    setCandidates([])
    setCandidateFrame(null)
    clearDownstreamState()
  }, [clearDownstreamState])

  const clearCaches = useCallback(async () => {
    await clearFrameCaches()
    refreshLibrary()
  }, [refreshLibrary])

  return useMemo(() => ({
    video,
    videoName,
    currentFrame,
    selection,
    selectionKind,
    selectionLoading,
    selectionError,
    candidates,
    features,
    library,
    trackJob,
    trackMessage,
    trackError,
    trackStarting,
    trackStartedAt,
    cropWindows,
    loading,
    loadingLabel,
    openError,
    framing,
    exportJob,
    stage,
    videoSwitchLocked,
    openUpload,
    openPath,
    openLibraryVideo,
    reExportLibraryTrack,
    refreshLibrary,
    selectAt,
    selectByDescription,
    confirmCandidate,
    setCurrentFrame,
    startTrack,
    retryTrack: startTrack,
    beginFraming: () => setFraming(true),
    setCropWindows: setCropWindowsState,
    setExportJob: setExportJobState,
    resetSelection,
    clearCaches,
  }), [
    candidates, clearCaches, confirmCandidate, cropWindows, currentFrame, exportJob,
    features, framing, library, loading, loadingLabel, openError, openLibraryVideo,
    openPath, openUpload, reExportLibraryTrack, refreshLibrary, resetSelection,
    selectAt, selectByDescription, selection, selectionError, selectionKind,
    selectionLoading, stage, startTrack, trackError, trackJob, trackMessage,
    trackStartedAt, trackStarting, video, videoName, videoSwitchLocked,
  ])
}

function filenameFromPath(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).at(-1) ?? path
}
