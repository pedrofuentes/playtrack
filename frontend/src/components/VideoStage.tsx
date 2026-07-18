import {
  forwardRef,
  type MouseEvent,
  type PointerEvent,
  type RefObject,
  type WheelEvent,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from 'react'

import {
  canvasRectFromSourceBox,
  containedMediaRect,
  displayedFrameIndex,
  type Point,
  type Size,
  sourcePointFromCanvas,
} from '../geometry'
import type {
  ClickSelection,
  CropWindow,
  LocateCandidate,
  TrackFrame,
} from '../api'
import { PlaybackOverlay } from './PlaybackOverlay'

export interface VideoStageProps {
  src: string
  sourceWidth: number
  sourceHeight: number
  fps: number
  frameCount: number
  selection: ClickSelection | null
  track: readonly TrackFrame[]
  cropWindows: readonly CropWindow[]
  candidates: readonly LocateCandidate[]
  playbackLocked: boolean
  selectionLocked?: boolean
  onSourceClick: (point: Point, frameIdx: number) => void
  onCandidateConfirm: (candidate: LocateCandidate, frameIdx: number) => void
  onFrameChange: (frameIdx: number) => void
}

export interface VideoStageHandle {
  pause(): number | null
  togglePlayback(): void
  seekToFrame(frameIdx: number): void
  stepFrames(delta: number): void
}

export interface ViewTransform {
  zoom: number
  x: number
  y: number
}

interface DragState {
  pointerId: number
  start: Point
  origin: Point
  moved: boolean
}

const MIN_VIEW_ZOOM = 1
const MAX_VIEW_ZOOM = 8
const DRAG_THRESHOLD_PX = 4

export function clampPan(pan: Point, zoom: number, viewport: Size): Point {
  if (
    !Number.isFinite(zoom) ||
    !Number.isFinite(viewport.width) ||
    !Number.isFinite(viewport.height) ||
    viewport.width <= 0 ||
    viewport.height <= 0
  ) {
    return { x: 0, y: 0 }
  }
  const clampedZoom = clamp(zoom, MIN_VIEW_ZOOM, MAX_VIEW_ZOOM)
  return {
    x: clamp(pan.x, viewport.width * (1 - clampedZoom), 0),
    y: clamp(pan.y, viewport.height * (1 - clampedZoom), 0),
  }
}

export function zoomAtPoint(
  view: ViewTransform,
  requestedZoom: number,
  point: Point,
  viewport: Size,
): ViewTransform {
  const zoom = clamp(requestedZoom, MIN_VIEW_ZOOM, MAX_VIEW_ZOOM)
  const ratio = zoom / view.zoom
  const pan = clampPan(
    {
      x: point.x - (point.x - view.x) * ratio,
      y: point.y - (point.y - view.y) * ratio,
    },
    zoom,
    viewport,
  )
  return { zoom, ...pan }
}

export function pointerMovedPastThreshold(
  start: Point,
  current: Point,
  threshold = DRAG_THRESHOLD_PX,
): boolean {
  return Math.hypot(current.x - start.x, current.y - start.y) > threshold
}

export const VideoStage = forwardRef<VideoStageHandle, VideoStageProps>(function VideoStage({
  src,
  sourceWidth,
  sourceHeight,
  fps,
  frameCount,
  selection,
  track,
  cropWindows,
  candidates,
  playbackLocked,
  selectionLocked = false,
  onSourceClick,
  onCandidateConfirm,
  onFrameChange,
}: VideoStageProps, forwardedRef) {
  const stageRef = useRef<HTMLDivElement>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [lastPoint, setLastPoint] = useState<Point | null>(null)
  const [view, setView] = useState<ViewTransform>({ zoom: 1, x: 0, y: 0 })
  const dragRef = useRef<DragState | null>(null)
  const suppressNextClickRef = useRef(false)
  const frozenFrameRef = useRef<number | null>(null)
  const viewRevision = `${view.zoom}:${view.x}:${view.y}`

  const seekToFrame = useCallback((frameIdx: number) => {
    const video = videoRef.current
    if (playbackLocked || !video || fps <= 0 || frameCount <= 0) return
    const clampedFrame = clamp(Math.round(frameIdx), 0, frameCount - 1)
    video.currentTime = clampedFrame / fps
    onFrameChange(clampedFrame)
  }, [fps, frameCount, onFrameChange, playbackLocked])

  const pauseAtDisplayedFrame = useCallback((): number | null => {
    const video = videoRef.current
    if (!video) return null
    video.pause()
    const frameIdx = playbackLocked && frozenFrameRef.current !== null
      ? frozenFrameRef.current
      : displayedFrameIndex(video.currentTime, fps, frameCount)
    frozenFrameRef.current = frameIdx
    if (fps > 0 && displayedFrameIndex(video.currentTime, fps, frameCount) !== frameIdx) {
      video.currentTime = frameIdx / fps
    }
    onFrameChange(frameIdx)
    return frameIdx
  }, [fps, frameCount, onFrameChange, playbackLocked])

  useImperativeHandle(forwardedRef, () => ({
    pause() {
      return pauseAtDisplayedFrame()
    },
    togglePlayback() {
      const video = videoRef.current
      if (!video || playbackLocked) return
      if (video.paused) void video.play()
      else video.pause()
    },
    seekToFrame,
    stepFrames(delta: number) {
      const video = videoRef.current
      if (!video || playbackLocked) return
      seekToFrame(Math.round(video.currentTime * fps) + delta)
    },
  }), [fps, pauseAtDisplayedFrame, playbackLocked, seekToFrame])

  const drawOverlay = useCallback(() => {
    drawOverlayCanvas(
      canvasRef,
      lastPoint,
      selection,
      candidates,
      sourceWidth,
      sourceHeight,
    )
  }, [candidates, lastPoint, selection, sourceHeight, sourceWidth])

  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    const observer = new ResizeObserver(drawOverlay)
    observer.observe(video)
    drawOverlay()
    return () => observer.disconnect()
  }, [drawOverlay])

  useEffect(() => {
    drawOverlay()
  }, [drawOverlay, viewRevision])

  useEffect(() => {
    setView({ zoom: 1, x: 0, y: 0 })
    setLastPoint(null)
    frozenFrameRef.current = null
    dragRef.current = null
    suppressNextClickRef.current = false
  }, [src])

  useEffect(() => {
    if (!playbackLocked) {
      frozenFrameRef.current = null
      return
    }
    const video = videoRef.current
    if (!video) return
    video.pause()
    if (frozenFrameRef.current === null) {
      frozenFrameRef.current = displayedFrameIndex(video.currentTime, fps, frameCount)
    }
  }, [fps, frameCount, playbackLocked])

  useEffect(() => {
    const stage = stageRef.current
    if (!stage) return
    const observer = new ResizeObserver(() => {
      const bounds = stage.getBoundingClientRect()
      setView((current) => {
        const pan = clampPan(current, current.zoom, bounds)
        if (pan.x === current.x && pan.y === current.y) return current
        return { ...current, ...pan }
      })
    })
    observer.observe(stage)
    return () => observer.disconnect()
  }, [])

  const handleClick = (event: MouseEvent<HTMLVideoElement>) => {
    if (suppressNextClickRef.current) {
      suppressNextClickRef.current = false
      return
    }
    if (selectionLocked) return
    const frameIdx = pauseAtDisplayedFrame()
    if (frameIdx === null) return
    const bounds = event.currentTarget.getBoundingClientRect()
    const point = sourcePointFromCanvas(
      { x: event.clientX - bounds.left, y: event.clientY - bounds.top },
      { width: bounds.width, height: bounds.height },
      { width: sourceWidth, height: sourceHeight },
    )
    if (!point) return
    const candidate = candidateAtSourcePoint(candidates, point)
    if (candidate) {
      setLastPoint(null)
      onCandidateConfirm(candidate, frameIdx)
      return
    }
    setLastPoint(point)
    console.info('PlayTrack source click', point)
    onSourceClick(point, frameIdx)
  }

  const handleWheel = (event: WheelEvent<HTMLDivElement>) => {
    event.preventDefault()
    const bounds = event.currentTarget.getBoundingClientRect()
    const point = { x: event.clientX - bounds.left, y: event.clientY - bounds.top }
    const scale = Math.exp(-event.deltaY * 0.0015)
    setView((current) => zoomAtPoint(current, current.zoom * scale, point, bounds))
  }

  const changeZoom = (amount: number) => {
    const bounds = stageRef.current?.getBoundingClientRect()
    if (!bounds) return
    setView((current) =>
      zoomAtPoint(
        current,
        current.zoom + amount,
        { x: bounds.width / 2, y: bounds.height / 2 },
        bounds,
      ),
    )
  }

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (view.zoom <= 1 || event.button !== 0) return
    dragRef.current = {
      pointerId: event.pointerId,
      start: { x: event.clientX, y: event.clientY },
      origin: { x: view.x, y: view.y },
      moved: false,
    }
  }

  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    const current = { x: event.clientX, y: event.clientY }
    if (!drag.moved && pointerMovedPastThreshold(drag.start, current)) {
      drag.moved = true
      event.currentTarget.setPointerCapture(event.pointerId)
    }
    if (!drag.moved) return
    event.preventDefault()
    const bounds = stageRef.current?.getBoundingClientRect()
    if (!bounds) return
    const pan = clampPan(
      {
        x: drag.origin.x + current.x - drag.start.x,
        y: drag.origin.y + current.y - drag.start.y,
      },
      view.zoom,
      bounds,
    )
    setView((currentView) => ({ ...currentView, ...pan }))
  }

  const finishPointer = (event: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    suppressNextClickRef.current = event.type === 'pointerup' && drag.moved
    dragRef.current = null
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }

  const reportFrame = () => {
    const video = videoRef.current
    if (!video) return
    const frozenFrame = frozenFrameRef.current
    if (playbackLocked && frozenFrame !== null) {
      const displayedFrame = displayedFrameIndex(video.currentTime, fps, frameCount)
      if (fps > 0 && displayedFrame !== frozenFrame) {
        video.currentTime = frozenFrame / fps
      }
      onFrameChange(frozenFrame)
      return
    }
    onFrameChange(displayedFrameIndex(video.currentTime, fps, frameCount))
  }

  return (
    <div ref={stageRef} className="video-stage" onWheel={handleWheel}>
      <div
        className={`video-transform${view.zoom > 1 ? ' is-pannable' : ''}${dragRef.current?.moved ? ' is-dragging' : ''}`}
        style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.zoom})` }}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={finishPointer}
        onPointerCancel={finishPointer}
      >
        <video
          ref={videoRef}
          src={src}
          controls
          playsInline
          preload="metadata"
          onClick={handleClick}
          onPlay={() => {
            if (playbackLocked) videoRef.current?.pause()
          }}
          onLoadedMetadata={reportFrame}
          onSeeking={reportFrame}
          onSeeked={reportFrame}
          onTimeUpdate={reportFrame}
        >
          Your browser does not support HTML video.
        </video>
        {selection?.maskPng && (
          <img
            className="selection-mask"
            src={`data:image/png;base64,${selection.maskPng}`}
            alt=""
            aria-hidden="true"
          />
        )}
        {selection && <span className="sr-only" role="status">Selected player</span>}
        <canvas ref={canvasRef} className="video-overlay" aria-hidden="true" />
        <PlaybackOverlay
          videoRef={videoRef}
          track={track}
          windows={cropWindows}
          sourceWidth={sourceWidth}
          sourceHeight={sourceHeight}
          fps={fps}
          frameCount={frameCount}
          viewRevision={viewRevision}
        />
      </div>
      <div className="view-controls" role="group" aria-label="Video view zoom">
        <button type="button" aria-label="Zoom out" onClick={() => changeZoom(-0.5)}>
          −
        </button>
        <output aria-label="View zoom">{Math.round(view.zoom * 100)}%</output>
        <button type="button" aria-label="Zoom in" onClick={() => changeZoom(0.5)}>
          +
        </button>
        <button
          type="button"
          className="reset-view"
          onClick={() => setView({ zoom: 1, x: 0, y: 0 })}
        >
          Reset
        </button>
      </div>
    </div>
  )
})

function drawOverlayCanvas(
  canvasRef: RefObject<HTMLCanvasElement | null>,
  point: Point | null,
  selection: ClickSelection | null,
  candidates: readonly LocateCandidate[],
  sourceWidth: number,
  sourceHeight: number,
) {
  const canvas = canvasRef.current
  const bounds = canvas?.getBoundingClientRect()
  if (!canvas || !bounds) return

  const pixelRatio = window.devicePixelRatio || 1
  canvas.width = Math.max(1, Math.round(bounds.width * pixelRatio))
  canvas.height = Math.max(1, Math.round(bounds.height * pixelRatio))
  const context = canvas.getContext('2d')
  if (!context) return
  context.scale(pixelRatio, pixelRatio)
  context.clearRect(0, 0, bounds.width, bounds.height)

  const media = containedMediaRect(
    { width: bounds.width, height: bounds.height },
    { width: sourceWidth, height: sourceHeight },
  )
  if (!media) return

  if (selection) {
    const box = canvasRectFromSourceBox(
      selection.box,
      { width: bounds.width, height: bounds.height },
      { width: sourceWidth, height: sourceHeight },
    )
    if (box) {
      context.strokeStyle = '#2fe1b4'
      context.lineWidth = 3
      context.strokeRect(box.left, box.top, box.width, box.height)
      const label = 'Selected player'
      context.font = '700 12px system-ui'
      const labelWidth = context.measureText(label).width + 12
      const labelTop = Math.max(2, box.top - 24)
      context.fillStyle = '#2fe1b4'
      context.fillRect(box.left, labelTop, labelWidth, 20)
      context.fillStyle = '#071b15'
      context.fillText(label, box.left + 6, labelTop + 14)
    }
  }

  candidates.forEach((candidate, index) => {
    const box = canvasRectFromSourceBox(
      candidate.box,
      { width: bounds.width, height: bounds.height },
      { width: sourceWidth, height: sourceHeight },
    )
    if (!box) return
    context.strokeStyle = '#ff5f8f'
    context.fillStyle = 'rgba(255, 95, 143, 0.16)'
    context.lineWidth = 3
    context.fillRect(box.left, box.top, box.width, box.height)
    context.strokeRect(box.left, box.top, box.width, box.height)
    context.fillStyle = '#ffedf3'
    context.font = '700 13px system-ui'
    context.fillText(String(index + 1), box.left + 5, box.top + 16)
  })

  if (point) {
    const x = media.left + point.x * media.scale
    const y = media.top + point.y * media.scale
    context.strokeStyle = '#ffcb66'
    context.fillStyle = 'rgba(255, 203, 102, 0.22)'
    context.lineWidth = 2
    context.beginPath()
    context.arc(x, y, 10, 0, Math.PI * 2)
    context.fill()
    context.stroke()
    context.beginPath()
    context.moveTo(x - 15, y)
    context.lineTo(x + 15, y)
    context.moveTo(x, y - 15)
    context.lineTo(x, y + 15)
    context.stroke()
  }
}

export function candidateAtSourcePoint(
  candidates: readonly LocateCandidate[],
  point: Point,
): LocateCandidate | null {
  return (
    candidates.find(({ box }) => {
      const [x1, y1, x2, y2] = box
      return point.x >= x1 && point.x < x2 && point.y >= y1 && point.y < y2
    }) ?? null
  )
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum)
}
