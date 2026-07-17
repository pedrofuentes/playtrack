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
  type LibraryTrack,
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
import {
  containsFrame,
  type FrameRange,
  normalizeFrameRange,
} from '../frameRange'
import { isJobActive, type WorkspaceStage, workspaceStage } from '../workflow'

const EXAMPLE_PATH = 'examples/example.mp4'

export interface WorkspaceController {
  video: VideoMetadata | null
  videoName: string | null
  currentFrame: number
  range: FrameRange
  selection: ClickSelection | null
  selectionKind: 'click' | 'text'
  selectionLoading: boolean
  selectionError: string | null
  candidates: LocateCandidate[]
  playerName: string
  features: FeatureFlags
  library: LibraryResponse
  trackJob: TrackJobUpdate | null
  trackMessage: string | null
  trackError: string | null
  trackStarting: boolean
  exportStarting: boolean
  trackStartedAt: number | null
  cropWindows: CropWindow[]
  loading: boolean
  loadingLabel: string
  openError: string | null
  framing: boolean
  exportJob: TrackJobUpdate | null
  stage: WorkspaceStage
  videoSwitchLocked: boolean
  openUpload(file: File, name?: string): Promise<void>
  openPath(path: string, name?: string): Promise<void>
  openLibraryVideo(video: LibraryVideo): Promise<void>
  openLibraryPlayer(video: LibraryVideo, player: LibraryTrack): Promise<boolean>
  refreshLibrary(): void
  selectAt(point: Point, frameIdx: number): void
  selectByDescription(prompt: string, frameIdx?: number): void
  confirmCandidate(candidate: LocateCandidate, frameIdx: number): void
  setPlayerName(name: string): void
  setCurrentFrame(frameIdx: number): void
  setRange(range: FrameRange): void
  setRangeIn(): void
  setRangeOut(): void
  resetRange(): void
  startTrack(): Promise<void>
  retryTrack(): Promise<void>
  beginFraming(): void
  setCropWindows(windows: CropWindow[]): void
  setExportJob(job: TrackJobUpdate | null): void
  beginExportSubmission(): number | null
  finishExportSubmission(token: number): void
  resetSelection(): void
  clearCaches(): Promise<void>
}

export function useWorkspace(): WorkspaceController {
  const [video, setVideo] = useState<VideoMetadata | null>(null)
  const [videoName, setVideoName] = useState<string | null>(null)
  const [currentFrame, setCurrentFrameState] = useState(0)
  const [range, setRangeState] = useState<FrameRange>({
    startFrameIdx: 0,
    endFrameExclusive: 1,
  })
  const [anchorFrame, setAnchorFrame] = useState<number | null>(null)
  const [selection, setSelection] = useState<ClickSelection | null>(null)
  const [selectionKind, setSelectionKind] = useState<'click' | 'text'>('click')
  const [selectionLoading, setSelectionLoading] = useState(false)
  const [selectionError, setSelectionError] = useState<string | null>(null)
  const [candidates, setCandidates] = useState<LocateCandidate[]>([])
  const [playerName, setPlayerNameState] = useState('')
  const [candidateFrame, setCandidateFrame] = useState<number | null>(null)
  const [features, setFeatures] = useState<FeatureFlags>({
    textSelection: { enabled: false, reason: '' },
  })
  const [library, setLibrary] = useState<LibraryResponse>({ videos: [], cacheBytes: 0 })
  const [trackJob, setTrackJob] = useState<TrackJobUpdate | null>(null)
  const [trackMessage, setTrackMessage] = useState<string | null>(null)
  const [trackError, setTrackError] = useState<string | null>(null)
  const [trackStarting, setTrackStarting] = useState(false)
  const [exportStarting, setExportStarting] = useState(false)
  const [trackStartedAt, setTrackStartedAt] = useState<number | null>(null)
  const [cropWindows, setCropWindowsState] = useState<CropWindow[]>([])
  const [loading, setLoading] = useState(true)
  const [loadingLabel, setLoadingLabel] = useState(`Opening ${EXAMPLE_PATH}…`)
  const [openError, setOpenError] = useState<string | null>(null)
  const [framing, setFraming] = useState(false)
  const [exportJob, setExportJobState] = useState<TrackJobUpdate | null>(null)
  const selectionRequest = useRef<AbortController | null>(null)
  const trackSocket = useRef<WebSocket | null>(null)
  const openGeneration = useRef(0)
  const exportSubmissionCounter = useRef(0)
  const exportSubmissionToken = useRef<number | null>(null)
  const rangeRef = useRef(range)
  rangeRef.current = range
  const trackStartingRef = useRef(trackStarting)
  trackStartingRef.current = trackStarting
  const loadingRef = useRef(loading)
  loadingRef.current = loading

  const stage = workspaceStage(selection, trackJob, framing)
  const videoSwitchLocked = trackStarting || exportStarting
    || isJobActive(trackJob) || isJobActive(exportJob)
  const videoSwitchLockedRef = useRef(videoSwitchLocked)
  videoSwitchLockedRef.current = videoSwitchLocked
  const stageRef = useRef(stage)
  stageRef.current = stage

  const beginExportSubmission = useCallback((): number | null => {
    if (
      exportSubmissionToken.current !== null
      || loadingRef.current || trackStartingRef.current || videoSwitchLockedRef.current
    ) return null
    const token = ++exportSubmissionCounter.current
    exportSubmissionToken.current = token
    setExportStarting(true)
    return token
  }, [])

  const finishExportSubmission = useCallback((token: number) => {
    if (exportSubmissionToken.current !== token) return
    exportSubmissionToken.current = null
    setExportStarting(false)
  }, [])

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

  const clearSelectionState = useCallback(() => {
    selectionRequest.current?.abort()
    selectionRequest.current = null
    setAnchorFrame(null)
    setSelection(null)
    setSelectionKind('click')
    setSelectionLoading(false)
    setSelectionError(null)
    setCandidates([])
    setPlayerNameState('')
    setCandidateFrame(null)
  }, [])

  const openVideo = useCallback(async (
    register: () => Promise<VideoMetadata>,
    fallbackName: string,
    activity: string,
    savedName?: string,
  ) => {
    if (
      exportSubmissionToken.current !== null
      || trackStartingRef.current || videoSwitchLockedRef.current
    ) return
    const generation = ++openGeneration.current
    loadingRef.current = true
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
    setPlayerNameState('')
    setCandidateFrame(null)
    try {
      const registered = await register()
      if (generation !== openGeneration.current) return
      setVideo(registered)
      setVideoName(savedName ?? registered.name)
      setRangeState({ startFrameIdx: 0, endFrameExclusive: registered.nbFrames })
    } catch (reason) {
      if (generation !== openGeneration.current) return
      setVideo(null)
      setVideoName(null)
      setOpenError(reason instanceof Error ? reason.message : `Could not open ${fallbackName}`)
    } finally {
      if (generation === openGeneration.current) {
        loadingRef.current = false
        setLoading(false)
      }
    }
  }, [clearDownstreamState])

  const refreshLibrary = useCallback(() => {
    void getLibrary().then(setLibrary).catch(() => {})
  }, [])

  const openPath = useCallback((path: string, name?: string) => openVideo(
    () => registerVideo(path, name),
    filenameFromPath(path),
    `Opening ${path}…`,
  ), [openVideo])

  const openUpload = useCallback((file: File, name?: string) => openVideo(
    () => uploadVideo(file, name),
    file.name,
    `Uploading ${file.name}…`,
  ), [openVideo])

  const openLibraryVideo = useCallback((saved: LibraryVideo) => openVideo(
    () => Promise.resolve(videoMetadataFromLibrary(saved)),
    saved.name,
    `Opening ${saved.name}…`,
    saved.name,
  ), [openVideo])

  const openLibraryPlayer = useCallback(async (
    saved: LibraryVideo,
    player: LibraryTrack,
  ): Promise<boolean> => {
    if (
      exportSubmissionToken.current !== null
      || trackStartingRef.current || videoSwitchLockedRef.current
    ) return false
    if (!saved.sourceExists) throw new Error('Source video is missing')
    const generation = ++openGeneration.current
    loadingRef.current = true
    setLoading(true)
    setLoadingLabel(`Opening ${player.name}…`)
    try {
      const restored = await getTrack(player.jobId)
      if (generation !== openGeneration.current) return false
      if (restored.state !== 'completed') {
        throw new Error('Saved player track is not complete')
      }
      const restoredRange = normalizeFrameRange({
        startFrameIdx: player.startFrameIdx ?? 0,
        endFrameExclusive: player.endFrameExclusive ?? saved.metadata.nbFrames,
      }, saved.metadata.nbFrames)
      if (!containsFrame(restoredRange, player.anchorFrameIdx)) {
        throw new Error('Saved player anchor is outside its tracked range')
      }

      selectionRequest.current?.abort()
      selectionRequest.current = null
      clearDownstreamState()
      setOpenError(null)
      setVideo(videoMetadataFromLibrary(saved))
      setVideoName(saved.name)
      setCurrentFrameState(player.anchorFrameIdx)
      setRangeState(restoredRange)
      setAnchorFrame(player.anchorFrameIdx)
      setSelection(null)
      setSelectionKind('click')
      setSelectionLoading(false)
      setSelectionError(null)
      setCandidates([])
      setCandidateFrame(null)
      setPlayerNameState(player.name)
      setTrackJob(restored)
      setTrackMessage(restored.message)
      setTrackError(null)
      setTrackStartedAt(null)
      setCropWindowsState([])
      setFraming(false)
      setExportJobState(null)
      return true
    } catch (reason) {
      if (generation !== openGeneration.current) return false
      throw reason
    } finally {
      if (generation === openGeneration.current) {
        loadingRef.current = false
        setLoading(false)
      }
    }
  }, [clearDownstreamState])

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
    openGeneration.current += 1
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
    setPlayerNameState('')
    setCandidateFrame(null)
    setSelectionError(null)
    clearDownstreamState()
    setSelectionLoading(true)
  }, [clearDownstreamState])

  const selectAt = useCallback((point: Point, frameIdx: number) => {
    if (loadingRef.current || trackStartingRef.current || !video) return
    if (!containsFrame(rangeRef.current, frameIdx)) {
      setSelectionError('Choose a frame inside the selected range')
      return
    }
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

  const selectByDescription = useCallback((rawPrompt: string, frameIdx?: number) => {
    const prompt = rawPrompt.trim()
    const selectionFrame = frameIdx ?? currentFrame
    if (loadingRef.current || trackStartingRef.current || !video || !prompt) return
    if (!containsFrame(rangeRef.current, selectionFrame)) {
      setSelectionError('Choose a frame inside the selected range')
      return
    }
    selectionRequest.current?.abort()
    const controller = new AbortController()
    selectionRequest.current = controller
    prepareSelection(selectionFrame, 'text')
    void selectByText(video.videoId, selectionFrame, prompt, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return
        setCandidates(result)
        setCandidateFrame(selectionFrame)
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
    if (loadingRef.current || trackStartingRef.current) return
    if (candidateFrame === null || frameIdx !== candidateFrame) {
      if (candidateFrame !== null) {
        setSelectionError(`Return to frame ${candidateFrame} to confirm this candidate`)
      }
      return
    }
    if (!containsFrame(rangeRef.current, frameIdx)) {
      setSelectionError('Choose a frame inside the selected range')
      return
    }
    setSelection({ box: candidate.box, score: candidate.score, maskPng: '' })
    setSelectionKind('text')
    setAnchorFrame(frameIdx)
    setCandidates([])
    setCandidateFrame(null)
    setSelectionError(null)
  }, [candidateFrame])

  const setCurrentFrame = useCallback((frameIdx: number) => {
    setCurrentFrameState(frameIdx)
    if (candidateFrame !== null && frameIdx !== candidateFrame) {
      setCandidates([])
      setCandidateFrame(null)
    }
  }, [candidateFrame])

  const setRange = useCallback((nextRange: FrameRange) => {
    if (
      loadingRef.current || trackStartingRef.current
      || !video || stageRef.current !== 'select'
    ) return
    const normalized = normalizeFrameRange(nextRange, video.nbFrames)
    const current = rangeRef.current
    if (
      normalized.startFrameIdx === current.startFrameIdx
      && normalized.endFrameExclusive === current.endFrameExclusive
    ) return
    clearSelectionState()
    rangeRef.current = normalized
    setRangeState(normalized)
  }, [clearSelectionState, video])

  const setRangeIn = useCallback(() => {
    setRange({ ...rangeRef.current, startFrameIdx: currentFrame })
  }, [currentFrame, setRange])

  const setRangeOut = useCallback(() => {
    setRange({ ...rangeRef.current, endFrameExclusive: currentFrame + 1 })
  }, [currentFrame, setRange])

  const resetRange = useCallback(() => {
    if (!video) return
    setRange({ startFrameIdx: 0, endFrameExclusive: video.nbFrames })
  }, [setRange, video])

  const startTrack = useCallback(async () => {
    if (
      loadingRef.current || trackStartingRef.current || !video || !selection || anchorFrame === null
      || !containsFrame(rangeRef.current, anchorFrame)
    ) return
    trackSocket.current?.close()
    trackSocket.current = null
    trackStartingRef.current = true
    setTrackStarting(true)
    setTrackStartedAt(Date.now())
    setTrackError(null)
    setTrackMessage('Starting SAM 2 video propagation…')
    setTrackJob(null)
    setCropWindowsState([])
    setFraming(false)
    setExportJobState(null)
    try {
      const { jobId, playerName: resolvedName } = await startTracking(
        video.videoId, anchorFrame, selection.box, playerName, rangeRef.current,
      )
      setPlayerNameState(resolvedName)
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
      trackStartingRef.current = false
      setTrackStarting(false)
    }
  }, [anchorFrame, playerName, refreshLibrary, selection, video])

  const resetSelection = useCallback(() => {
    if (loadingRef.current || trackStartingRef.current) return
    clearSelectionState()
    clearDownstreamState()
  }, [clearDownstreamState, clearSelectionState])

  const setPlayerName = useCallback((name: string) => {
    if (loadingRef.current || trackStartingRef.current) return
    setPlayerNameState(name)
  }, [])

  const clearCaches = useCallback(async () => {
    await clearFrameCaches()
    refreshLibrary()
  }, [refreshLibrary])

  return useMemo(() => ({
    video,
    videoName,
    currentFrame,
    range,
    selection,
    selectionKind,
    selectionLoading,
    selectionError,
    candidates,
    playerName,
    features,
    library,
    trackJob,
    trackMessage,
    trackError,
    trackStarting,
    exportStarting,
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
    openLibraryPlayer,
    refreshLibrary,
    selectAt,
    selectByDescription,
    confirmCandidate,
    setPlayerName,
    setCurrentFrame,
    setRange,
    setRangeIn,
    setRangeOut,
    resetRange,
    startTrack,
    retryTrack: startTrack,
    beginFraming: () => setFraming(true),
    setCropWindows: setCropWindowsState,
    setExportJob: setExportJobState,
    beginExportSubmission,
    finishExportSubmission,
    resetSelection,
    clearCaches,
  }), [
    beginExportSubmission, candidates, clearCaches, confirmCandidate, cropWindows, currentFrame,
    exportJob, exportStarting, finishExportSubmission,
    features, framing, library, loading, loadingLabel, openError, openLibraryPlayer,
    openLibraryVideo, openPath, openUpload, range, refreshLibrary, resetRange, resetSelection,
    playerName, selectAt, selectByDescription, selection, selectionError, selectionKind,
    selectionLoading, setPlayerName, setRange, setRangeIn, setRangeOut, stage, startTrack, trackError, trackJob, trackMessage,
    trackStartedAt, trackStarting, video, videoName, videoSwitchLocked,
  ])
}

function filenameFromPath(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).at(-1) ?? path
}

function videoMetadataFromLibrary(saved: LibraryVideo): VideoMetadata {
  return { ...saved.metadata, name: saved.name }
}
