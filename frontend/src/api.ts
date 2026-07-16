export interface VideoMetadata {
  videoId: string
  width: number
  height: number
  fps: number
  nbFrames: number
  duration: number
}

export async function registerVideo(path: string): Promise<VideoMetadata> {
  const response = await fetch('/api/videos', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  })
  if (!response.ok) {
    let message = `Could not open video (${response.status})`
    try {
      const payload = (await response.json()) as { detail?: string }
      if (payload.detail) message = payload.detail
    } catch {
      // Keep the status-based message if the response is not JSON.
    }
    throw new Error(message)
  }
  return (await response.json()) as VideoMetadata
}

export function videoFileUrl(videoId: string): string {
  return `/api/videos/${encodeURIComponent(videoId)}/file`
}

