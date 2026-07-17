import { useCallback, useEffect, useRef, useState } from 'react'

import {
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
  videoFileUrl,
  watchTrackJob,
  uploadVideo,
} from './api'
import { VideoStage } from './components/VideoStage'
import { ExportPanel } from './components/ExportPanel'
import { OpenVideoPanel } from './components/OpenVideoPanel'
import { LibraryPanel } from './components/LibraryPanel'
import type { Point } from './geometry'

const EXAMPLE_PATH = 'examples/example.mp4'

export default function App() {
  const [video, setVideo] = useState<VideoMetadata | null>(null)
  const [videoName, setVideoName] = useState<string | null>(null)
  const [lastClick, setLastClick] = useState<Point | null>(null)
  const [lastFrame, setLastFrame] = useState<number | null>(null)
  const [currentFrame, setCurrentFrame] = useState(0)
  const [selection, setSelection] = useState<ClickSelection | null>(null)
  const [selectionKind, setSelectionKind] = useState<'click' | 'text'>('click')
  const [selectionLoading, setSelectionLoading] = useState(false)
  const [selectionError, setSelectionError] = useState<string | null>(null)
  const [textPrompt, setTextPrompt] = useState('')
  const [candidates, setCandidates] = useState<LocateCandidate[]>([])
  const [candidateFrame, setCandidateFrame] = useState<number | null>(null)
  const [features, setFeatures] = useState<FeatureFlags>({
    textSelection: { enabled: false, reason: '' },
  })
  const [library, setLibrary] = useState<LibraryResponse>({ videos: [], cacheBytes: 0 })
  const [trackMessage, setTrackMessage] = useState<string | null>(null)
  const [trackJob, setTrackJob] = useState<TrackJobUpdate | null>(null)
  const [trackStarting, setTrackStarting] = useState(false)
  const [trackError, setTrackError] = useState<string | null>(null)
  const [cropWindows, setCropWindows] = useState<CropWindow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingLabel, setLoadingLabel] = useState(`Opening ${EXAMPLE_PATH}…`)
  const selectionRequest = useRef<AbortController | null>(null)
  const trackSocket = useRef<WebSocket | null>(null)

  const openVideo = useCallback(async (
    register: () => Promise<VideoMetadata>,
    filename: string,
    activity: string,
  ) => {
    selectionRequest.current?.abort()
    selectionRequest.current = null
    trackSocket.current?.close()
    trackSocket.current = null
    setLoading(true)
    setLoadingLabel(activity)
    setError(null)
    setLastClick(null)
    setLastFrame(null)
    setCurrentFrame(0)
    setSelection(null)
    setSelectionKind('click')
    setSelectionLoading(false)
    setSelectionError(null)
    setCandidates([])
    setCandidateFrame(null)
    setTrackMessage(null)
    setTrackJob(null)
    setTrackStarting(false)
    setTrackError(null)
    setCropWindows([])
    try {
      setVideo(await register())
      setVideoName(filename)
    } catch (reason) {
      setVideo(null)
      setVideoName(null)
      setError(reason instanceof Error ? reason.message : `Could not open ${filename}`)
    } finally {
      setLoading(false)
    }
  }, [])

  const openExample = useCallback(
    () => openVideo(
      () => registerVideo(EXAMPLE_PATH),
      filenameFromPath(EXAMPLE_PATH),
      `Opening ${EXAMPLE_PATH}…`,
    ),
    [openVideo],
  )

  const refreshLibrary = useCallback(() => {
    void getLibrary().then(setLibrary).catch(() => {})
  }, [])

  const openPath = useCallback(
    (path: string) => openVideo(
      () => registerVideo(path),
      filenameFromPath(path),
      `Opening ${path}…`,
    ),
    [openVideo],
  )

  const openUpload = useCallback(
    (file: File) => openVideo(
      () => uploadVideo(file),
      file.name,
      `Uploading ${file.name}…`,
    ),
    [openVideo],
  )

  useEffect(() => {
    void openExample()
    refreshLibrary()
    void getFeatures()
      .then(setFeatures)
      .catch(() => {
        setFeatures({
          textSelection: {
            enabled: false,
            reason: 'Feature status is unavailable',
          },
        })
      })
  }, [openExample, refreshLibrary])

  const openLibraryVideo = useCallback((saved: LibraryVideo) => {
    void openVideo(
      () => Promise.resolve(saved.metadata),
      libraryVideoName(saved),
      `Opening ${libraryVideoName(saved)}…`,
    )
  }, [openVideo])

  const reExportLibraryTrack = useCallback(async (saved: LibraryVideo, jobId: string) => {
    await openVideo(() => Promise.resolve(saved.metadata), libraryVideoName(saved), `Opening ${libraryVideoName(saved)}…`)
    try {
      const restored = await getTrack(jobId)
      setTrackJob(restored)
      setTrackMessage(restored.message)
      setTrackError(restored.state === 'failed' ? restored.message : null)
    } catch (reason) {
      setTrackError(reason instanceof Error ? reason.message : 'Could not restore saved track')
    }
  }, [openVideo])

  useEffect(
    () => () => {
      selectionRequest.current?.abort()
      trackSocket.current?.close()
    },
    [],
  )

  const handleSourceClick = useCallback(
    (point: Point, frameIdx: number) => {
      if (!video) return
      selectionRequest.current?.abort()
      trackSocket.current?.close()
      trackSocket.current = null
      const controller = new AbortController()
      selectionRequest.current = controller
      setLastClick(point)
      setLastFrame(frameIdx)
      setSelection(null)
      setSelectionKind('click')
      setCandidates([])
      setCandidateFrame(null)
      setSelectionError(null)
      setTrackMessage(null)
      setTrackJob(null)
      setTrackStarting(false)
      setTrackError(null)
      setCropWindows([])
      setSelectionLoading(true)
      void selectByClick(
        video.videoId,
        frameIdx,
        point.x,
        point.y,
        controller.signal,
      )
        .then((result) => {
          if (!controller.signal.aborted) setSelection(result)
        })
        .catch((reason: unknown) => {
          if (controller.signal.aborted) return
          setSelectionError(
            reason instanceof Error ? reason.message : 'Could not select player',
          )
        })
        .finally(() => {
          if (selectionRequest.current === controller) {
            selectionRequest.current = null
            setSelectionLoading(false)
          }
        })
    },
    [video],
  )

  const handleTextSelect = useCallback(() => {
    const prompt = textPrompt.trim()
    if (!video || !prompt) return
    selectionRequest.current?.abort()
    trackSocket.current?.close()
    trackSocket.current = null
    const controller = new AbortController()
    selectionRequest.current = controller
    setLastClick(null)
    setLastFrame(currentFrame)
    setSelection(null)
    setSelectionKind('text')
    setCandidates([])
    setCandidateFrame(null)
    setSelectionError(null)
    setTrackMessage(null)
    setTrackJob(null)
    setTrackStarting(false)
    setTrackError(null)
    setCropWindows([])
    setSelectionLoading(true)
    void selectByText(video.videoId, currentFrame, prompt, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return
        setCandidates(result)
        setCandidateFrame(currentFrame)
        if (result.length === 0) {
          setSelectionError('No players matched that prompt')
        }
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return
        setSelectionError(
          reason instanceof Error ? reason.message : 'Could not ground text prompt',
        )
      })
      .finally(() => {
        if (selectionRequest.current === controller) {
          selectionRequest.current = null
          setSelectionLoading(false)
        }
      })
  }, [currentFrame, textPrompt, video])

  const handleCandidateConfirm = useCallback(
    (candidate: LocateCandidate, frameIdx: number) => {
      setSelection({ box: candidate.box, score: candidate.score, maskPng: '' })
      setSelectionKind('text')
      setLastFrame(frameIdx)
      setCandidates([])
      setCandidateFrame(null)
      setSelectionError(null)
    },
    [],
  )

  const handleFrameChange = useCallback(
    (frameIdx: number) => {
      setCurrentFrame(frameIdx)
      if (candidateFrame !== null && frameIdx !== candidateFrame) {
        setCandidates([])
        setCandidateFrame(null)
      }
    },
    [candidateFrame],
  )

  const handleTrack = useCallback(async () => {
    if (!video || !selection || lastFrame === null) return
    trackSocket.current?.close()
    trackSocket.current = null
    setTrackStarting(true)
    setTrackError(null)
    setTrackMessage('Starting SAM 2 video propagation…')
    setTrackJob(null)
    setCropWindows([])
    try {
      const { jobId } = await startTracking(
        video.videoId,
        lastFrame,
        selection.box,
      )
      const socket = watchTrackJob(
        jobId,
        (update) => {
          setTrackJob(update)
          setTrackMessage(update.message)
          if (update.state === 'failed') setTrackError(update.message)
          if (update.state === 'completed' || update.state === 'failed') {
            if (trackSocket.current === socket) trackSocket.current = null
            socket.close()
          }
        },
        (message) => {
          setTrackError(message)
          setTrackMessage(null)
        },
      )
      trackSocket.current = socket
    } catch (reason) {
      setTrackError(
        reason instanceof Error ? reason.message : 'Could not start tracking',
      )
      setTrackMessage(null)
    } finally {
      setTrackStarting(false)
    }
  }, [lastFrame, selection, video])

  const workflowStep = currentWorkflowStep(selection, trackJob)
  const exportReady = Boolean(video && trackJob?.state === 'completed')

  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <p className="eyebrow">Panoramic player tracking</p>
          <h1>FindMe</h1>
        </div>
        <p className="intro">
          Open any sports video, zoom in to identify a player, then track and export them.
        </p>
      </header>

      <section className="workspace" aria-live="polite">
        {video ? (
            <VideoStage
              src={videoFileUrl(video.videoId)}
              sourceWidth={video.width}
              sourceHeight={video.height}
              fps={video.fps}
              frameCount={video.nbFrames}
              selection={selection}
              track={trackJob?.track ?? []}
              cropWindows={cropWindows}
              candidates={candidates}
              onSourceClick={handleSourceClick}
              onCandidateConfirm={handleCandidateConfirm}
              onFrameChange={handleFrameChange}
            />
        ) : (
          <div className={`status-panel${error ? ' error-panel' : ''}`}>
            {loading ? <p>{loadingLabel}</p> : error ? (
              <>
                <p>{error}</p>
                <button type="button" onClick={() => void openExample()}>Retry example</button>
              </>
            ) : <p>Choose a video to begin.</p>}
          </div>
        )}
        <aside className="details-panel">
          <OpenVideoPanel
            disabled={loading}
            onUpload={openUpload}
            onOpenPath={openPath}
          />
          <LibraryPanel
            library={library}
            onOpenVideo={openLibraryVideo}
            onReExport={(saved, jobId) => { void reExportLibraryTrack(saved, jobId) }}
            onRefresh={refreshLibrary}
          />
          <nav className="workflow-steps" aria-label="FindMe workflow">
            <ol>
              {(['Select player', 'Track', 'Export'] as const).map((label, index) => {
                const step = index + 1
                return (
                  <li
                    key={label}
                    className={step === workflowStep ? 'is-current' : step < workflowStep ? 'is-complete' : ''}
                    aria-current={step === workflowStep ? 'step' : undefined}
                  >
                    <span>{step}</span>{label}
                  </li>
                )
              })}
            </ol>
          </nav>
          {video && (
            <>
              <div className="video-name">
                <p className="label">Video</p>
                <p className="value" title={videoName ?? undefined}>{videoName}</p>
              </div>
              <div>
                <p className="label">Source</p>
                <p className="value">{video.width} × {video.height}</p>
              </div>
              <div>
                <p className="label">Frame rate</p>
                <p className="value">{formatNumber(video.fps)} fps</p>
              </div>
              <div>
                <p className="label">Frames</p>
                <p className="value">{video.nbFrames.toLocaleString()}</p>
              </div>
              <div>
                <p className="label">Duration</p>
                <p className="value">{formatNumber(video.duration)} s</p>
              </div>
              <div className="coordinate-readout">
                <p className="label">Last source click</p>
                <p className="value" data-testid="source-coordinates">
                  {lastClick
                    ? `x ${lastClick.x} · y ${lastClick.y} · frame ${lastFrame}`
                    : 'Click inside the picture'}
                </p>
                <p className="hint">Coordinates are logged to the browser console too.</p>
              </div>
              <div className="selection-readout">
                <p className="label">Player selection</p>
                {features.textSelection.enabled && (
                  <form
                    className="text-selection-form"
                    onSubmit={(event) => {
                      event.preventDefault()
                      handleTextSelect()
                    }}
                  >
                    <label htmlFor="player-prompt">Find by description</label>
                    <div>
                      <input
                        id="player-prompt"
                        type="text"
                        value={textPrompt}
                        maxLength={500}
                        placeholder="the player in the white jersey"
                        onChange={(event) => setTextPrompt(event.target.value)}
                      />
                      <button
                        type="submit"
                        disabled={selectionLoading || !textPrompt.trim()}
                      >
                        Find
                      </button>
                    </div>
                  </form>
                )}
                {selectionLoading && <p className="value">Finding player…</p>}
                {selectionError && <p className="selection-error">{selectionError}</p>}
                {candidates.length > 0 && (
                  <p className="hint">
                    {candidates.length} candidate{candidates.length === 1 ? '' : 's'} found.
                    Click a pink box in the video to confirm.
                  </p>
                )}
                {selection && (
                  <>
                    <p className="value selection-score">
                      {selectionKind === 'click' ? 'Mask' : 'Candidate'} score{' '}
                      {(selection.score * 100).toFixed(1)}%
                    </p>
                    <button
                      type="button"
                      disabled={
                        trackStarting ||
                        trackJob?.state === 'queued' ||
                        trackJob?.state === 'running'
                      }
                      onClick={() => void handleTrack()}
                    >
                      {trackStarting || trackJob?.state === 'running'
                        ? 'Tracking…'
                        : 'Track this player'}
                    </button>
                  </>
                )}
                {!selection && !selectionLoading && !selectionError && (
                  <p className="hint">
                    Click a player for a SAM 2 mask
                    {features.textSelection.enabled ? ', or describe one above.' : '.'}
                  </p>
                )}
                {trackMessage && <p className="hint track-message">{trackMessage}</p>}
                {trackJob && (
                  <progress
                    className="tracking-progress"
                    max={1}
                    value={trackJob.progress}
                    aria-label="Tracking progress"
                  />
                )}
                {trackError && <p className="selection-error">{trackError}</p>}
              </div>
            </>
          )}
          <ExportPanel
            key={`${video?.videoId ?? 'none'}:${trackJob?.jobId ?? 'none'}`}
            videoId={video?.videoId ?? ''}
            trackJobId={trackJob?.jobId ?? ''}
            disabled={!exportReady}
            onPlanChange={setCropWindows}
          />
        </aside>
      </section>
    </main>
  )
}

export function currentWorkflowStep(
  selection: ClickSelection | null,
  trackJob: TrackJobUpdate | null,
): 1 | 2 | 3 {
  if (trackJob?.state === 'completed') return 3
  if (selection) return 2
  return 1
}

export function libraryVideoName(video: Pick<LibraryVideo, 'name'>): string {
  return video.name
}

function filenameFromPath(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).at(-1) ?? path
}

function formatNumber(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(2)
}
