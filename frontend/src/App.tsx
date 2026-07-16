import { useCallback, useEffect, useState } from 'react'

import { registerVideo, type VideoMetadata, videoFileUrl } from './api'
import { VideoStage } from './components/VideoStage'
import type { Point } from './geometry'

const EXAMPLE_PATH = 'examples/example.mp4'

export default function App() {
  const [video, setVideo] = useState<VideoMetadata | null>(null)
  const [lastClick, setLastClick] = useState<Point | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const openExample = useCallback(async () => {
    setLoading(true)
    setError(null)
    setLastClick(null)
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

  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <p className="eyebrow">M0 · Video I/O</p>
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
              onSourceClick={setLastClick}
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
                  {lastClick ? `x ${lastClick.x} · y ${lastClick.y}` : 'Click inside the picture'}
                </p>
                <p className="hint">Coordinates are logged to the browser console too.</p>
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

