import {
  type MouseEvent,
  type RefObject,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react'

import {
  containedMediaRect,
  type Point,
  sourcePointFromCanvas,
} from '../geometry'

interface VideoStageProps {
  src: string
  sourceWidth: number
  sourceHeight: number
  onSourceClick: (point: Point) => void
}

export function VideoStage({
  src,
  sourceWidth,
  sourceHeight,
  onSourceClick,
}: VideoStageProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [lastPoint, setLastPoint] = useState<Point | null>(null)

  const drawOverlay = useCallback(() => {
    drawClickMarker(canvasRef, lastPoint, sourceWidth, sourceHeight)
  }, [lastPoint, sourceHeight, sourceWidth])

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
    setLastPoint(point)
    console.info('FindMe source click', point)
    onSourceClick(point)
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
      >
        Your browser does not support HTML video.
      </video>
      <canvas ref={canvasRef} className="video-overlay" aria-hidden="true" />
    </div>
  )
}

function drawClickMarker(
  canvasRef: RefObject<HTMLCanvasElement | null>,
  point: Point | null,
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
  if (!point) return

  const media = containedMediaRect(
    { width: bounds.width, height: bounds.height },
    { width: sourceWidth, height: sourceHeight },
  )
  if (!media) return
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

