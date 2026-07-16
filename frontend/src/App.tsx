import { useCallback, useEffect, useRef, useState } from 'react'

import {
  type ClickSelection,
  registerVideo,
  selectByClick,
  startTracking,
  type TrackJobUpdate,
  type VideoMetadata,
  videoFileUrl,
  watchTrackJob,
} from './api'
import { VideoStage } from './components/VideoStage'
import type { Point } from './geometry'

const EXAMPLE_PATH = 'examples/example.mp4'

export default function App() {
  const [video, setVideo] = useState<VideoMetadata | null>(null)
  const [lastClick, setLastClick] = useState<Point | null>(null)
  const [lastFrame, setLastFrame] = useState<number | null>(null)
  const [selection, setSelection] = useState<ClickSelection | null>(null)
  const [selectionLoading, setSelectionLoading] = useState(false)
  const [selectionError, setSelectionError] = useState<string | null>(null)
  const [trackMessage, setTrackMessage] = useState<string | null>(null)
  const [trackJob, setTrackJob] = useState<TrackJobUpdate | null>(null)
  const [trackStarting, setTrackStarting] = useState(false)
  const [trackError, setTrackError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const selectionRequest = useRef<AbortController | null>(null)
  const trackSocket = useRef<WebSocket | null>(null)

  const openExample = useCallback(async () => {
    selectionRequest.current?.abort()
    selectionRequest.current = null
    trackSocket.current?.close()
    trackSocket.current = null
    setLoading(true)
    setError(null)
    setLastClick(null)
    setLastFrame(null)
    setSelection(null)
    setSelectionLoading(false)
    setSelectionError(null)
    setTrackMessage(null)
    setTrackJob(null)
    setTrackStarting(false)
    setTrackError(null)
    try {
      setVideo(await registerVideo(EXAMPLE_PATH))
    } catch (reason) {
      setVideo(null)
      setError(reason instanceof Error ? reason.message : 'Could not open the example video')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void openExample()
  }, [openExample])

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
      setSelectionError(null)
      setTrackMessage(null)
      setTrackJob(null)
      setTrackStarting(false)
      setTrackError(null)
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

  const handleTrack = useCallback(async () => {
    if (!video || !selection || lastFrame === null) return
    trackSocket.current?.close()
    trackSocket.current = null
    setTrackStarting(true)
    setTrackError(null)
    setTrackMessage('Starting SAM 2 video propagation…')
    setTrackJob(null)
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

  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <p className="eyebrow">M2 · Video tracking</p>
          <h1>FindMe</h1>
        </div>
        <p className="intro">Open the panoramic match, scrub to any frame, then click a player.</p>
      </header>

      <section className="workspace" aria-live="polite">
        {loading && <div className="status-panel">Opening {EXAMPLE_PATH}…</div>}
        {error && (
          <div className="status-panel error-panel">
            <p>{error}</p>
            <button type="button" onClick={() => void openExample()}>Retry</button>
          </div>
        )}
        {video && (
          <>
            <VideoStage
              src={videoFileUrl(video.videoId)}
              sourceWidth={video.width}
              sourceHeight={video.height}
              fps={video.fps}
              frameCount={video.nbFrames}
              selection={selection}
              track={trackJob?.track ?? []}
              onSourceClick={handleSourceClick}
            />
            <aside className="details-panel">
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
                {selectionLoading && <p className="value">Finding player…</p>}
                {selectionError && <p className="selection-error">{selectionError}</p>}
                {selection && (
                  <>
                    <p className="value selection-score">
                      Mask score {(selection.score * 100).toFixed(1)}%
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
                  <p className="hint">Click a player to request a SAM 2 mask.</p>
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
            </aside>
          </>
        )}
      </section>
    </main>
  )
}

function formatNumber(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(2)
}
