import { useState } from 'react'

import {
  clearFrameCaches,
  deleteLibraryExport,
  deleteLibraryTrack,
  deleteLibraryVideo,
  exportDownloadUrl,
  type LibraryResponse,
  type LibraryVideo,
} from '../api'

interface LibraryPanelProps {
  library: LibraryResponse
  onOpenVideo: (video: LibraryVideo) => void
  onReExport: (video: LibraryVideo, jobId: string) => void
  onRefresh: () => void
}

export function LibraryPanel({ library, onOpenVideo, onReExport, onRefresh }: LibraryPanelProps) {
  const [expanded, setExpanded] = useState(true)
  const [busy, setBusy] = useState(false)
  const run = async (action: () => Promise<void>) => {
    setBusy(true)
    try { await action(); onRefresh() } finally { setBusy(false) }
  }
  return (
    <section className="library-panel">
      <button type="button" className="library-toggle" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded}>
        Library ({library.videos.length})
      </button>
      {expanded && <div className="library-content">
        <button type="button" disabled={busy} onClick={() => void run(async () => { await clearFrameCaches() })}>
          Clear frame caches ({formatBytes(library.cacheBytes)})
        </button>
        {library.videos.map((video) => <article className="library-video" key={video.videoId}>
          <div><strong>{video.name}</strong><span>{formatBytes(video.size)} · {formatDate(video.openedAt)}</span></div>
          <div className="library-actions">
            <button type="button" disabled={busy || !video.sourceExists} onClick={() => onOpenVideo(video)}>Open</button>
            <button type="button" disabled={busy} onClick={() => {
              if (window.confirm(`Delete ${video.name} and its saved tracks/exports?`)) void run(async () => { await deleteLibraryVideo(video.videoId) })
            }}>Delete</button>
          </div>
          {video.tracks.map((track) => <div className="library-item" key={track.jobId}>
            <span>Anchor {track.anchorFrameIdx} · {track.frameCount} frames · {track.lostCount} lost</span>
            <div className="library-actions"><button type="button" disabled={busy || !video.sourceExists} onClick={() => onReExport(video, track.jobId)}>Re-export</button><button type="button" disabled={busy} onClick={() => {
              if (window.confirm('Delete this saved track and its exports?')) void run(async () => { await deleteLibraryTrack(track.jobId) })
            }}>Delete</button></div>
          </div>)}
          {video.exports.map((item) => <div className="library-item" key={item.exportId}>
            <span>{item.params.outWidth ?? '?'} × {item.params.outHeight ?? '?'} · {formatBytes(item.size)}</span>
            <div className="library-actions">{item.sourceExists && <a href={exportDownloadUrl(item.exportId)} download>Download</a>}<button type="button" disabled={busy} onClick={() => {
              if (window.confirm('Delete this export?')) void run(async () => { await deleteLibraryExport(item.exportId) })
            }}>Delete</button></div>
          </div>)}
        </article>)}
        {library.videos.length === 0 && <p className="hint">No saved videos yet.</p>}
      </div>}
    </section>
  )
}

function formatBytes(bytes: number): string { return `${(bytes / (1024 * 1024)).toFixed(1)} MB` }
function formatDate(value: string | null): string { return value ? new Date(value).toLocaleDateString() : 'Unknown date' }
