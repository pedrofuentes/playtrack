import { type RefObject, useCallback, useEffect, useMemo, useRef } from 'react'

import type { CropWindow, TrackFrame } from '../api'
import type { SourceBox } from '../geometry'
import { canvasRectFromSourceBox, displayedFrameIndex } from '../geometry'

interface PlaybackGeometry {
  frameIdx: number
  playerBox: SourceBox | null
  cropWindow: CropWindow | null
}

export function playbackGeometryAtTime(
  track: readonly TrackFrame[],
  windows: readonly CropWindow[],
  currentTime: number,
  fps: number,
  frameCount: number,
): PlaybackGeometry {
  const frameIdx = displayedFrameIndex(currentTime, fps, frameCount)
  const frame = track.find((candidate) => candidate.frameIdx === frameIdx)
  return {
    frameIdx,
    playerBox: frame && !frame.lost ? frame.box : null,
    cropWindow: windows.find((window) => window.frameIdx === frameIdx) ?? null,
  }
}

interface PlaybackOverlayProps {
  videoRef: RefObject<HTMLVideoElement | null>
  track: readonly TrackFrame[]
  windows: readonly CropWindow[]
  sourceWidth: number
  sourceHeight: number
  fps: number
  frameCount: number
  viewRevision?: string
}

export function PlaybackOverlay({
  videoRef,
  track,
  windows,
  sourceWidth,
  sourceHeight,
  fps,
  frameCount,
  viewRevision = '',
}: PlaybackOverlayProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const framesByIndex = useMemo(
    () => new Map(track.map((frame) => [frame.frameIdx, frame])),
    [track],
  )
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
    if (crop) {
      const projected = canvasRectFromSourceBox(
        [crop.x, crop.y, crop.x + crop.w, crop.y + crop.h],
        bounds,
        { width: sourceWidth, height: sourceHeight },
      )
      if (projected) {
        context.strokeStyle = '#ffcb66'
        context.fillStyle = 'rgba(255, 203, 102, 0.06)'
        context.lineWidth = 2
        context.setLineDash([8, 6])
        context.fillRect(projected.left, projected.top, projected.width, projected.height)
        context.strokeRect(projected.left, projected.top, projected.width, projected.height)
        context.setLineDash([])
      }
    }

    const frame = framesByIndex.get(frameIdx)
    if (!frame || frame.lost || !frame.box) return
    const player = canvasRectFromSourceBox(
      frame.box,
      bounds,
      { width: sourceWidth, height: sourceHeight },
    )
    if (!player) return
    context.strokeStyle = '#ff5f8f'
    context.fillStyle = 'rgba(255, 95, 143, 0.12)'
    context.lineWidth = 3
    context.fillRect(player.left, player.top, player.width, player.height)
    context.strokeRect(player.left, player.top, player.width, player.height)
  }, [fps, frameCount, framesByIndex, sourceHeight, sourceWidth, videoRef, windowsByIndex])

  useEffect(() => draw(), [draw, viewRevision])

  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    let animationFrame = 0
    const cancelLoop = () => window.cancelAnimationFrame(animationFrame)
    const tick = () => {
      draw()
      if (!video.paused && !video.ended) animationFrame = window.requestAnimationFrame(tick)
    }
    const startLoop = () => { cancelLoop(); tick() }
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

  return <canvas ref={canvasRef} className="playback-overlay" aria-hidden="true" />
}
