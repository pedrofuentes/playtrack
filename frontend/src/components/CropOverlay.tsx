import {
  type RefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
} from 'react'

import type { CropWindow } from '../api'
import { canvasRectFromSourceBox, displayedFrameIndex } from '../geometry'

interface CropOverlayProps {
  videoRef: RefObject<HTMLVideoElement | null>
  windows: readonly CropWindow[]
  sourceWidth: number
  sourceHeight: number
  fps: number
  frameCount: number
}

export function cropWindowAtTime(
  windows: readonly CropWindow[],
  currentTime: number,
  fps: number,
  frameCount: number,
): CropWindow | null {
  const frameIdx = displayedFrameIndex(currentTime, fps, frameCount)
  return windows.find((window) => window.frameIdx === frameIdx) ?? null
}

export function CropOverlay({
  videoRef,
  windows,
  sourceWidth,
  sourceHeight,
  fps,
  frameCount,
}: CropOverlayProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const windowsByIndex = useMemo(
    () => new Map(windows.map((window) => [window.frameIdx, window])),
    [windows],
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
    const crop = windowsByIndex.get(frameIdx)
    if (!crop) return
    const projected = canvasRectFromSourceBox(
      [crop.x, crop.y, crop.x + crop.w, crop.y + crop.h],
      { width: bounds.width, height: bounds.height },
      { width: sourceWidth, height: sourceHeight },
    )
    if (!projected) return
    context.strokeStyle = '#ffcb66'
    context.fillStyle = 'rgba(255, 203, 102, 0.06)'
    context.lineWidth = 2
    context.setLineDash([8, 6])
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
  }, [fps, frameCount, sourceHeight, sourceWidth, videoRef, windowsByIndex])

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

  return <canvas ref={canvasRef} className="crop-overlay" aria-hidden="true" />
}
