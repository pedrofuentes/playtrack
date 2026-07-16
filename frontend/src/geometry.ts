export interface Point {
  x: number
  y: number
}

export interface Size {
  width: number
  height: number
}

export interface ContainedMediaRect extends Size {
  left: number
  top: number
  scale: number
}

export type SourceBox = readonly [number, number, number, number]

export interface CanvasRect {
  left: number
  top: number
  width: number
  height: number
}

export function containedMediaRect(
  container: Size,
  source: Size,
): ContainedMediaRect | null {
  if (
    !isValidDimension(container.width) ||
    !isValidDimension(container.height) ||
    !isValidDimension(source.width) ||
    !isValidDimension(source.height)
  ) {
    return null
  }

  const scale = Math.min(
    container.width / source.width,
    container.height / source.height,
  )
  const width = source.width * scale
  const height = source.height * scale
  return {
    left: (container.width - width) / 2,
    top: (container.height - height) / 2,
    width,
    height,
    scale,
  }
}

export function sourcePointFromCanvas(
  point: Point,
  container: Size,
  source: Size,
): Point | null {
  const media = containedMediaRect(container, source)
  if (
    media === null ||
    !Number.isFinite(point.x) ||
    !Number.isFinite(point.y) ||
    point.x < media.left ||
    point.x > media.left + media.width ||
    point.y < media.top ||
    point.y > media.top + media.height
  ) {
    return null
  }

  return {
    x: clamp(Math.round((point.x - media.left) / media.scale), 0, source.width - 1),
    y: clamp(Math.round((point.y - media.top) / media.scale), 0, source.height - 1),
  }
}

export function displayedFrameIndex(
  currentTime: number,
  fps: number,
  frameCount: number,
): number {
  if (
    !Number.isFinite(currentTime) ||
    !Number.isFinite(fps) ||
    fps <= 0 ||
    !Number.isInteger(frameCount) ||
    frameCount <= 0
  ) {
    return 0
  }
  return clamp(Math.floor(Math.max(0, currentTime) * fps + 1e-6), 0, frameCount - 1)
}

export function canvasRectFromSourceBox(
  box: SourceBox,
  container: Size,
  source: Size,
): CanvasRect | null {
  const media = containedMediaRect(container, source)
  const [x1, y1, x2, y2] = box
  if (
    media === null ||
    ![x1, y1, x2, y2].every(Number.isFinite) ||
    x1 < 0 ||
    y1 < 0 ||
    x1 >= x2 ||
    y1 >= y2 ||
    x2 > source.width ||
    y2 > source.height
  ) {
    return null
  }
  return {
    left: media.left + x1 * media.scale,
    top: media.top + y1 * media.scale,
    width: (x2 - x1) * media.scale,
    height: (y2 - y1) * media.scale,
  }
}

function isValidDimension(value: number): boolean {
  return Number.isFinite(value) && value > 0
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum)
}
