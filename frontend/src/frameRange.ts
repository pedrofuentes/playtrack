export interface FrameRange {
  startFrameIdx: number
  endFrameExclusive: number
}

export function normalizeFrameRange(range: FrameRange, frameCount: number): FrameRange {
  const safeFrameCount = Math.max(1, Math.floor(frameCount))
  const startFrameIdx = clamp(Math.floor(range.startFrameIdx), 0, safeFrameCount - 1)
  const endFrameExclusive = clamp(
    Math.floor(range.endFrameExclusive),
    startFrameIdx + 1,
    safeFrameCount,
  )
  return { startFrameIdx, endFrameExclusive }
}

export function frameRangeCount(range: FrameRange): number {
  return Math.max(0, range.endFrameExclusive - range.startFrameIdx)
}

export function containsFrame(range: FrameRange, frameIdx: number): boolean {
  return frameIdx >= range.startFrameIdx && frameIdx < range.endFrameExclusive
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum)
}
