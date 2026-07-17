import {
  type MouseEvent,
  type RefObject,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react'

import {
  canvasRectFromSourceBox,
  containedMediaRect,
  displayedFrameIndex,
  type Point,
  sourcePointFromCanvas,
} from '../geometry'
import type {
  ClickSelection,
  CropWindow,
  LocateCandidate,
  TrackFrame,
} from '../api'
import { CropOverlay } from './CropOverlay'
import { TrackOverlay } from './TrackOverlay'

interface VideoStageProps {
  src: string
  sourceWidth: number
  sourceHeight: number
  fps: number
  frameCount: number
  selection: ClickSelection | null
  track: readonly TrackFrame[]
  cropWindows: readonly CropWindow[]
  candidates: readonly LocateCandidate[]
  onSourceClick: (point: Point, frameIdx: number) => void
  onCandidateConfirm: (candidate: LocateCandidate, frameIdx: number) => void
  onFrameChange: (frameIdx: number) => void
}

export function VideoStage({
  src,
  sourceWidth,
  sourceHeight,
  fps,
  frameCount,
  selection,
  track,
  cropWindows,
  candidates,
  onSourceClick,
  onCandidateConfirm,
  onFrameChange,
}: VideoStageProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [lastPoint, setLastPoint] = useState<Point | null>(null)

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

  const handleClick = (event: MouseEvent<HTMLVideoElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    const point = sourcePointFromCanvas(
      { x: event.clientX - bounds.left, y: event.clientY - bounds.top },
      { width: bounds.width, height: bounds.height },
      { width: sourceWidth, height: sourceHeight },
    )
    if (!point) return
    const frameIdx = displayedFrameIndex(
      event.currentTarget.currentTime,
      fps,
      frameCount,
    )
    const candidate = candidateAtSourcePoint(candidates, point)
    if (candidate) {
      setLastPoint(null)
      onCandidateConfirm(candidate, frameIdx)
      return
    }
    setLastPoint(point)
    console.info('FindMe source click', point)
    onSourceClick(point, frameIdx)
  }

  const reportFrame = () => {
    const video = videoRef.current
    if (video) {
      onFrameChange(displayedFrameIndex(video.currentTime, fps, frameCount))
    }
  }

  return (
    <div className="video-stage">
      <video
        ref={videoRef}
        src={src}
        controls
        playsInline
        preload="metadata"
        onClick={handleClick}
        onLoadedMetadata={reportFrame}
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
      <canvas ref={canvasRef} className="video-overlay" aria-hidden="true" />
      <TrackOverlay
        videoRef={videoRef}
        track={track}
        sourceWidth={sourceWidth}
        sourceHeight={sourceHeight}
        fps={fps}
        frameCount={frameCount}
      />
      <CropOverlay
        videoRef={videoRef}
        windows={cropWindows}
        sourceWidth={sourceWidth}
        sourceHeight={sourceHeight}
        fps={fps}
        frameCount={frameCount}
      />
    </div>
  )
}

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
