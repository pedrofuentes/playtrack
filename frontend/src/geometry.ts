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

function isValidDimension(value: number): boolean {
  return Number.isFinite(value) && value > 0
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum)
}
