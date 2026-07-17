import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from 'react'

import {
  type CropWindow,
  exportDownloadUrl,
  type ExportSettings,
  fetchCropPlan,
  startExport,
  type TrackJobUpdate,
  watchTrackJob,
} from '../api'

export const EXPORT_PRESETS = [
  { key: '1920x1080', label: '1080p', detail: '1920 × 1080', width: 1920, height: 1080 },
  { key: '1280x720', label: '720p', detail: '1280 × 720', width: 1280, height: 720 },
  { key: 'custom', label: 'Custom', detail: 'Even dimensions', width: null, height: null },
] as const

export interface ExportPanelHandle {
  triggerExport(): void
}

interface ExportPanelProps {
  videoId: string
  trackJobId: string
  disabled?: boolean
  exportStarting: boolean
  onExportStart: () => number | null
  onExportFinish: (token: number) => void
  onPlanChange: (windows: CropWindow[]) => void
  onJobChange?: (job: TrackJobUpdate | null) => void
  onLibraryChange?: () => void
}

export const ExportPanel = forwardRef<ExportPanelHandle, ExportPanelProps>(function ExportPanel({
  videoId,
  trackJobId,
  disabled = false,
  exportStarting,
  onExportStart,
  onExportFinish,
  onPlanChange,
  onJobChange = () => {},
  onLibraryChange = () => {},
}, forwardedRef) {
  const [preset, setPreset] = useState('1280x720')
  const [outWidth, setOutWidth] = useState(1280)
  const [outHeight, setOutHeight] = useState(720)
  const [zoom, setZoom] = useState(1)
  const [responsiveness, setResponsiveness] = useState(0.5)
  const [maxAccelPxPerFrame2, setMaxAccelPxPerFrame2] = useState(3)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [job, setJob] = useState<TrackJobUpdate | null>(null)
  const [error, setError] = useState<string | null>(null)
  const socketRef = useRef<WebSocket | null>(null)
  const mountedRef = useRef(true)
  const requestGenerationRef = useRef(0)
  const activeSubmissionRef = useRef<{ generation: number; token: number } | null>(null)

  const settings = useMemo<ExportSettings>(() => ({
    outWidth,
    outHeight,
    zoom,
    smoothing: { responsiveness, maxAccelPxPerFrame2 },
  }), [maxAccelPxPerFrame2, outHeight, outWidth, responsiveness, zoom])
  const validDimensions = outWidth >= 2 && outHeight >= 2 && outWidth % 2 === 0 && outHeight % 2 === 0

  useEffect(() => {
    if (disabled || !videoId || !trackJobId || !validDimensions) {
      onPlanChange([])
      setPreviewLoading(false)
      return
    }
    const controller = new AbortController()
    setPreviewLoading(true)
    setError(null)
    const timer = window.setTimeout(() => {
      void fetchCropPlan(videoId, trackJobId, settings, controller.signal)
        .then((preview) => onPlanChange(preview.windows.map((window) => ({
          ...window,
          frameIdx: preview.sourceStartFrame + window.frameIdx,
        }))))
        .catch((reason: unknown) => {
          if (controller.signal.aborted) return
          onPlanChange([])
          setError(reason instanceof Error ? reason.message : 'Could not preview crop')
        })
        .finally(() => {
          if (!controller.signal.aborted) setPreviewLoading(false)
        })
    }, 150)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [disabled, onPlanChange, settings, trackJobId, validDimensions, videoId])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      requestGenerationRef.current += 1
      socketRef.current?.close()
      socketRef.current = null
      const active = activeSubmissionRef.current
      activeSubmissionRef.current = null
      if (active) onExportFinish(active.token)
      onPlanChange([])
    }
  }, [onExportFinish, onPlanChange])

  const choosePreset = (key: string) => {
    setPreset(key)
    const selected = EXPORT_PRESETS.find((candidate) => candidate.key === key)
    if (selected?.width && selected.height) {
      setOutWidth(selected.width)
      setOutHeight(selected.height)
    }
  }

  const beginExport = useCallback(async () => {
    if (
      disabled || !validDimensions || previewLoading || exportStarting
      || activeSubmissionRef.current !== null
    ) return
    const token = onExportStart()
    if (token === null) return
    const generation = ++requestGenerationRef.current
    activeSubmissionRef.current = { generation, token }
    const isCurrent = () => (
      mountedRef.current && requestGenerationRef.current === generation
    )
    socketRef.current?.close()
    socketRef.current = null
    setJob(null)
    onJobChange(null)
    setError(null)
    try {
      const { jobId } = await startExport(videoId, trackJobId, settings)
      if (!isCurrent()) return
      const queued: TrackJobUpdate = {
        jobId,
        state: 'queued',
        progress: 0,
        message: 'Export queued…',
        track: [],
      }
      setJob(queued)
      onJobChange(queued)
      let socket: WebSocket
      try {
        socket = watchTrackJob(
          jobId,
          (update) => {
            if (!isCurrent()) return
            setJob(update)
            onJobChange(update)
            if (update.state === 'failed') setError(update.message)
            if (update.state === 'completed' || update.state === 'failed') {
              if (socketRef.current === socket) socketRef.current = null
              socket.close()
              if (update.state === 'completed') onLibraryChange()
            }
          },
          (message) => {
            if (!isCurrent()) return
            setError(message)
            setJob((current) => {
              const failed = current ? { ...current, state: 'failed' as const, message } : null
              onJobChange(failed)
              return failed
            })
          },
        )
      } catch (reason) {
        if (!isCurrent()) return
        const message = reason instanceof Error ? reason.message : 'Could not watch export'
        const failed = { ...queued, state: 'failed' as const, message }
        setError(message)
        setJob(failed)
        onJobChange(failed)
        return
      }
      socketRef.current = socket
    } catch (reason) {
      if (isCurrent()) {
        setError(reason instanceof Error ? reason.message : 'Could not start export')
      }
    } finally {
      const active = activeSubmissionRef.current
      if (active?.generation === generation && active.token === token) {
        activeSubmissionRef.current = null
        onExportFinish(token)
      }
    }
  }, [
    disabled, exportStarting, onExportFinish, onExportStart, onJobChange,
    onLibraryChange, previewLoading, settings, trackJobId, validDimensions, videoId,
  ])

  useImperativeHandle(forwardedRef, () => ({
    triggerExport() {
      void beginExport()
    },
  }), [beginExport])

  if (disabled) return null
  const exporting = exportStarting || job?.state === 'queued' || job?.state === 'running'

  return (
    <section className="export-panel">
      {job?.state !== 'completed' && (
        <fieldset disabled={exporting}>
          <legend className="sr-only">Output settings</legend>
          <p className="section-label">Format</p>
          <div className="export-presets">
            {EXPORT_PRESETS.map((option) => (
              <button
                key={option.key}
                type="button"
                className={preset === option.key ? 'is-active' : ''}
                aria-pressed={preset === option.key}
                onClick={() => choosePreset(option.key)}
              >
                <strong>{option.label}</strong>
                <span>{option.detail}</span>
              </button>
            ))}
          </div>
          <label className="range-control">
            <span>Zoom <output>{zoom.toFixed(1)}×</output></span>
            <input type="range" min={1} max={4} step={0.1} value={zoom} onChange={(event) => setZoom(Number(event.target.value))} />
          </label>
          <label className="range-control">
            <span>Camera smoothness <output>{responsiveness.toFixed(1)} s</output></span>
            <input type="range" min={0.2} max={1.5} step={0.1} value={responsiveness} onChange={(event) => setResponsiveness(Number(event.target.value))} />
            <small>Framing widens automatically when needed to keep the player visible.</small>
          </label>
          <details className="advanced-settings">
            <summary>Advanced settings</summary>
            {preset === 'custom' && (
              <div className="dimension-inputs">
                <label>Width<input type="number" min={2} step={2} value={outWidth} onChange={(event) => setOutWidth(Number(event.target.value))} /></label>
                <span>×</span>
                <label>Height<input type="number" min={2} step={2} value={outHeight} onChange={(event) => setOutHeight(Number(event.target.value))} /></label>
              </div>
            )}
            <label>
              Max acceleration (px/frame²)
              <input type="number" min={0.1} step={1} value={maxAccelPxPerFrame2} onChange={(event) => setMaxAccelPxPerFrame2(Number(event.target.value))} />
            </label>
          </details>
          {!validDimensions && <p className="inline-error">Dimensions must be positive even numbers.</p>}
          {previewLoading && <p className="operation-status">Updating crop preview…</p>}
          <button type="button" className="primary-action" disabled={!validDimensions || previewLoading || exporting} onClick={() => void beginExport()}>
            {exporting ? 'Exporting…' : 'Export MP4'}
          </button>
        </fieldset>
      )}
      {job && job.state !== 'completed' && (
        <div className="export-job" aria-live="polite">
          <p>{job.message}</p>
          <progress max={1} value={job.progress} aria-label="Export progress" />
        </div>
      )}
      {job?.state === 'completed' && (
        <div className="export-complete">
          <p className="section-label">Export complete</p>
          <h3>Your video is ready</h3>
          <a className="download-link primary-action" href={exportDownloadUrl(job.jobId)} download>Download MP4</a>
          <button type="button" className="secondary-action" onClick={() => {
            setJob(null)
            onJobChange(null)
            setError(null)
          }}>Export another version</button>
        </div>
      )}
      {error && <p className="inline-error">{error}</p>}
    </section>
  )
})
