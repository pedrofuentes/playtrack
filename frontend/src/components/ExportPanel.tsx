import { useEffect, useMemo, useRef, useState } from 'react'

import {
  exportDownloadUrl,
  type ExportSettings,
  fetchCropPlan,
  startExport,
  type TrackJobUpdate,
  watchTrackJob,
} from '../api'
import type { CropWindow } from '../api'

export const EXPORT_PRESETS = [
  { key: '1920x1080', label: '1920 × 1080', width: 1920, height: 1080 },
  { key: '1280x720', label: '1280 × 720', width: 1280, height: 720 },
  { key: 'custom', label: 'Custom', width: null, height: null },
] as const

interface ExportPanelProps {
  videoId: string
  trackJobId: string
  disabled?: boolean
  onPlanChange: (windows: CropWindow[]) => void
}

export function ExportPanel({
  videoId,
  trackJobId,
  disabled = false,
  onPlanChange,
}: ExportPanelProps) {
  const [preset, setPreset] = useState('1280x720')
  const [outWidth, setOutWidth] = useState(1280)
  const [outHeight, setOutHeight] = useState(720)
  const [zoom, setZoom] = useState(1)
  const [windowSec, setWindowSec] = useState(0.8)
  const [deadZonePx, setDeadZonePx] = useState(30)
  const [maxVelPxPerFrame, setMaxVelPxPerFrame] = useState(28)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [exportStarting, setExportStarting] = useState(false)
  const [job, setJob] = useState<TrackJobUpdate | null>(null)
  const [error, setError] = useState<string | null>(null)
  const socketRef = useRef<WebSocket | null>(null)

  const settings = useMemo<ExportSettings>(
    () => ({
      outWidth,
      outHeight,
      zoom,
      smoothing: { windowSec, deadZonePx, maxVelPxPerFrame },
    }),
    [deadZonePx, maxVelPxPerFrame, outHeight, outWidth, windowSec, zoom],
  )
  const validDimensions =
    outWidth >= 2 && outHeight >= 2 && outWidth % 2 === 0 && outHeight % 2 === 0

  useEffect(() => {
    if (disabled || !videoId || !trackJobId || !validDimensions) {
      onPlanChange([])
      setPreviewLoading(false)
      return
    }
    const controller = new AbortController()
    setPreviewLoading(true)
    setError(null)
    void fetchCropPlan(videoId, trackJobId, settings, controller.signal)
      .then((preview) => onPlanChange(preview.windows))
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return
        onPlanChange([])
        setError(reason instanceof Error ? reason.message : 'Could not preview crop')
      })
      .finally(() => {
        if (!controller.signal.aborted) setPreviewLoading(false)
      })
    return () => controller.abort()
  }, [disabled, onPlanChange, settings, trackJobId, validDimensions, videoId])

  useEffect(
    () => () => {
      socketRef.current?.close()
      onPlanChange([])
    },
    [onPlanChange],
  )

  const choosePreset = (key: string) => {
    setPreset(key)
    const selected = EXPORT_PRESETS.find((candidate) => candidate.key === key)
    if (selected?.width && selected.height) {
      setOutWidth(selected.width)
      setOutHeight(selected.height)
    }
  }

  const beginExport = async () => {
    if (disabled || !validDimensions) return
    socketRef.current?.close()
    setExportStarting(true)
    setJob(null)
    setError(null)
    try {
      const { jobId } = await startExport(videoId, trackJobId, settings)
      const socket = watchTrackJob(
        jobId,
        (update) => {
          setJob(update)
          if (update.state === 'failed') setError(update.message)
          if (update.state === 'completed' || update.state === 'failed') {
            if (socketRef.current === socket) socketRef.current = null
            socket.close()
          }
        },
        setError,
      )
      socketRef.current = socket
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not start export')
    } finally {
      setExportStarting(false)
    }
  }

  const exporting = exportStarting || job?.state === 'queued' || job?.state === 'running'

  return (
    <section className={`export-panel${disabled ? ' is-disabled' : ''}`} aria-disabled={disabled}>
      <p className="label">Virtual camera export</p>
      {disabled && (
        <p className="export-locked-hint">
          Select a player and track them first — then export a video that follows them.
        </p>
      )}
      <fieldset disabled={disabled}>
        <label>
          Resolution
          <select value={preset} onChange={(event) => choosePreset(event.target.value)}>
            {EXPORT_PRESETS.map((option) => (
              <option key={option.key} value={option.key}>{option.label}</option>
            ))}
          </select>
        </label>
        {preset === 'custom' && (
          <div className="dimension-inputs">
            <label>
              Width
              <input
                type="number"
                min={2}
                step={2}
                value={outWidth}
                onChange={(event) => setOutWidth(Number(event.target.value))}
              />
            </label>
            <span>×</span>
            <label>
              Height
              <input
                type="number"
                min={2}
                step={2}
                value={outHeight}
                onChange={(event) => setOutHeight(Number(event.target.value))}
              />
            </label>
          </div>
        )}
        <label>
          Zoom <output>{zoom.toFixed(1)}×</output>
          <input
            type="range"
            min={1}
            max={4}
            step={0.1}
            value={zoom}
            onChange={(event) => setZoom(Number(event.target.value))}
          />
        </label>
        <div className="smoothing-grid">
          <label>
            Window (sec)
            <input
              type="number"
              min={0}
              step={0.1}
              value={windowSec}
              onChange={(event) => setWindowSec(Number(event.target.value))}
            />
          </label>
          <label>
            Dead zone (px)
            <input
              type="number"
              min={0}
              step={1}
              value={deadZonePx}
              onChange={(event) => setDeadZonePx(Number(event.target.value))}
            />
          </label>
          <label>
            Max speed (px/frame)
            <input
              type="number"
              min={1}
              step={1}
              value={maxVelPxPerFrame}
              onChange={(event) => setMaxVelPxPerFrame(Number(event.target.value))}
            />
          </label>
        </div>
        {!validDimensions && <p className="selection-error">Dimensions must be positive even numbers.</p>}
        {previewLoading && <p className="hint">Updating crop preview…</p>}
        <button
          type="button"
          disabled={!validDimensions || previewLoading || exporting}
          onClick={() => void beginExport()}
        >
          {exporting ? 'Exporting…' : 'Export cropped video'}
        </button>
      </fieldset>
      {job && (
        <>
          <p className="hint">{job.message}</p>
          <progress max={1} value={job.progress} aria-label="Export progress" />
        </>
      )}
      {job?.state === 'completed' && (
        <a className="download-link" href={exportDownloadUrl(job.jobId)} download>
          Download MP4
        </a>
      )}
      {error && <p className="selection-error">{error}</p>}
    </section>
  )
}
