import {
  type RefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
} from 'react'

import type { TrackFrame } from '../api'
import { canvasRectFromSourceBox, displayedFrameIndex } from '../geometry'

interface TrackOverlayProps {
  videoRef: RefObject<HTMLVideoElement | null>
  track: readonly TrackFrame[]
  sourceWidth: number
  sourceHeight: number
  fps: number
  frameCount: number
}

export function trackFrameAtTime(
  track: readonly TrackFrame[],
  currentTime: number,
  fps: number,
  frameCount: number,
): TrackFrame | null {
  const frameIdx = displayedFrameIndex(currentTime, fps, frameCount)
  const frame = track.find((candidate) => candidate.frameIdx === frameIdx)
  return frame && !frame.lost && frame.box ? frame : null
}

export function TrackOverlay({
  videoRef,
  track,
  sourceWidth,
  sourceHeight,
  fps,
  frameCount,
}: TrackOverlayProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const framesByIndex = useMemo(
    () => new Map(track.map((frame) => [frame.frameIdx, frame])),
    [track],
  )

  const draw = useCallback(() => {
    const video = videoRef.current
    const canvas = canvasRef.current
    const bounds = canvas?.getBoundingClientRect()
    if (!video || !canvas || !bounds) return

    const pixelRatio = window.devicePixelRatio || 1
    canvas.width = Math.max(1, Math.round(bounds.width * pixelRatio))
    canvas.height = Math.max(1, Math.round(bounds.height * pixelRatio))
    const context = canvas.getContext('2d')
    if (!context) return
    context.scale(pixelRatio, pixelRatio)
    context.clearRect(0, 0, bounds.width, bounds.height)

    const frameIdx = displayedFrameIndex(video.currentTime, fps, frameCount)
    const frame = framesByIndex.get(frameIdx)
    if (!frame || frame.lost || !frame.box) return
    const projected = canvasRectFromSourceBox(
      frame.box,
      { width: bounds.width, height: bounds.height },
      { width: sourceWidth, height: sourceHeight },
    )
    if (!projected) return

    context.strokeStyle = '#ff5f8f'
    context.fillStyle = 'rgba(255, 95, 143, 0.12)'
    context.lineWidth = 3
    context.fillRect(
      projected.left,
      projected.top,
      projected.width,
      projected.height,
    )
    context.strokeRect(
      projected.left,
      projected.top,
      projected.width,
      projected.height,
    )
  }, [fps, frameCount, framesByIndex, sourceHeight, sourceWidth, videoRef])

  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    let animationFrame = 0

    const cancelLoop = () => window.cancelAnimationFrame(animationFrame)
    const tick = () => {
      draw()
      if (!video.paused && !video.ended) {
        animationFrame = window.requestAnimationFrame(tick)
      }
    }
    const startLoop = () => {
      cancelLoop()
      tick()
    }
    const observer = new ResizeObserver(draw)
    observer.observe(video)
    for (const event of ['play', 'pause', 'timeupdate', 'seeking', 'seeked']) {
      video.addEventListener(event, startLoop)
    }
    startLoop()
    return () => {
      cancelLoop()
      observer.disconnect()
      for (const event of ['play', 'pause', 'timeupdate', 'seeking', 'seeked']) {
        video.removeEventListener(event, startLoop)
      }
    }
  }, [draw, videoRef])

  return <canvas ref={canvasRef} className="track-overlay" aria-hidden="true" />
}
