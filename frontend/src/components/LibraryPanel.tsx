import { useMemo, useState } from 'react'

import {
  deleteLibraryExport,
  deleteLibraryTrack,
  deleteLibraryVideo,
  exportDownloadUrl,
  type LibraryResponse,
  type LibraryVideo,
} from '../api'

interface LibraryPanelProps {
  library: LibraryResponse
  openingDisabled?: boolean
  onOpenVideo: (video: LibraryVideo) => void
  onReExport: (video: LibraryVideo, jobId: string) => void
  onRefresh: () => void
}

export function LibraryPanel({
  library,
  openingDisabled = false,
  onOpenVideo,
  onReExport,
  onRefresh,
}: LibraryPanelProps) {
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const videos = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase()
    return normalized
      ? library.videos.filter((video) => video.name.toLocaleLowerCase().includes(normalized))
      : library.videos
  }, [library.videos, query])

  const run = async (action: () => Promise<void>) => {
    setBusy(true)
    try {
      await action()
      onRefresh()
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="library-panel">
      <label className="library-search">
        <span className="sr-only">Search videos and exports</span>
        <input
          type="search"
          value={query}
          placeholder="Search videos"
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>
      <p className="section-label">Recent videos</p>
      <div className="library-list">
        {videos.map((video) => (
          <article className="library-video" key={video.videoId}>
            <div className="library-video-row">
              <div className="library-thumbnail" aria-hidden="true" />
              <div className="library-video-copy">
                <strong title={video.name}>{video.name}</strong>
                <span>
                  {video.sourceKind === 'upload' ? 'Uploaded copy' : 'Registered path'} ·{' '}
                  {video.tracks.length} track{video.tracks.length === 1 ? '' : 's'} ·{' '}
                  {video.exports.length} export{video.exports.length === 1 ? '' : 's'}
                </span>
                <span>{formatBytes(video.size)} · {formatDate(video.openedAt)}</span>
              </div>
              <button
                type="button"
                disabled={busy || openingDisabled || !video.sourceExists}
                onClick={() => onOpenVideo(video)}
              >
                Open
              </button>
            </div>
            <details>
              <summary>Tracks and exports</summary>
              <div className="library-records">
                {video.tracks.map((track) => (
                  <div className="library-item" key={track.jobId}>
                    <span>Anchor {track.anchorFrameIdx} · {track.frameCount} frames · {track.lostCount} lost</span>
                    <div className="library-actions">
                      <button
                        type="button"
                        disabled={busy || openingDisabled || !video.sourceExists}
                        onClick={() => onReExport(video, track.jobId)}
                      >
                        Re-export
                      </button>
                      <button type="button" className="danger" disabled={busy} onClick={() => {
                        if (window.confirm('Delete this saved track and its exports?')) {
                          void run(() => deleteLibraryTrack(track.jobId))
                        }
                      }}>Delete</button>
                    </div>
                  </div>
                ))}
                {video.exports.map((item) => (
                  <div className="library-item" key={item.exportId}>
                    <span>{item.params.outWidth ?? '?'} × {item.params.outHeight ?? '?'} · {formatBytes(item.size)}</span>
                    <div className="library-actions">
                      {item.sourceExists && <a href={exportDownloadUrl(item.exportId)} download>Download</a>}
                      <button type="button" className="danger" disabled={busy} onClick={() => {
                        if (window.confirm('Delete this export?')) {
                          void run(() => deleteLibraryExport(item.exportId))
                        }
                      }}>Delete</button>
                    </div>
                  </div>
                ))}
              </div>
            </details>
            <button type="button" className="library-delete danger" disabled={busy} onClick={() => {
              if (window.confirm(`Delete ${video.name} and its saved tracks/exports?`)) {
                void run(() => deleteLibraryVideo(video.videoId))
              }
            }}>Delete video record</button>
          </article>
        ))}
        {videos.length === 0 && (
          <p className="empty-copy">{library.videos.length === 0 ? 'No saved videos yet.' : 'No videos match your search.'}</p>
        )}
      </div>
    </section>
  )
}

function formatBytes(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleDateString() : 'Unknown date'
}
