import { useMemo, useState } from 'react'

import {
  deleteLibraryExport,
  deleteLibraryTrack,
  deleteLibraryVideo,
  exportDownloadUrl,
  type LibraryResponse,
  type LibraryTrack,
  type LibraryVideo,
  renameLibraryPlayer,
  renameLibrarySource,
} from '../api'

type LibraryTab = 'sources' | 'players' | 'exports'

interface LibraryPanelProps {
  library: LibraryResponse
  openingDisabled?: boolean
  onOpenVideo: (video: LibraryVideo) => void
  onOpenPlayer: (video: LibraryVideo, player: LibraryTrack) => Promise<boolean>
  onRefresh: () => void
}

export function LibraryPanel({
  library,
  openingDisabled = false,
  onOpenVideo,
  onOpenPlayer,
  onRefresh,
}: LibraryPanelProps) {
  const [tab, setTab] = useState<LibraryTab>('sources')
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const [sourceRenaming, setSourceRenaming] = useState<string | null>(null)
  const [sourceName, setSourceName] = useState('')
  const [playerRenaming, setPlayerRenaming] = useState<string | null>(null)
  const [playerName, setPlayerName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const normalized = query.trim().toLocaleLowerCase()

  const sources = useMemo(() => library.videos.filter((video) => (
    !normalized || video.name.toLocaleLowerCase().includes(normalized)
  )), [library.videos, normalized])
  const players = useMemo(() => library.videos.flatMap((video) => (
    video.tracks.map((player) => ({ video, player }))
  )).filter(({ video, player }) => (
    !normalized || `${player.name} ${video.name}`.toLocaleLowerCase().includes(normalized)
  )), [library.videos, normalized])
  const exports = useMemo(() => library.videos.flatMap((video) => (
    video.exports.map((item) => ({
      video,
      item,
      player: video.tracks.find((candidate) => candidate.jobId === item.trackJobId),
    }))
  )).filter(({ video, player }) => (
    !normalized || `${player?.name ?? ''} ${video.name}`.toLocaleLowerCase().includes(normalized)
  )), [library.videos, normalized])

  const run = async (action: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
      onRefresh()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Library action failed')
    } finally {
      setBusy(false)
    }
  }

  const savePlayerName = (player: LibraryTrack) => run(async () => {
    await renameLibraryPlayer(player.jobId, playerName)
    setPlayerRenaming(null)
  })

  const saveSourceName = (video: LibraryVideo) => run(async () => {
    await renameLibrarySource(video.videoId, sourceName.trim())
    setSourceRenaming(null)
  })

  const openPlayer = async (video: LibraryVideo, player: LibraryTrack) => {
    setBusy(true)
    setError(null)
    try {
      await onOpenPlayer(video, player)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not open player')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="library-panel">
      <div className="library-tabs" role="tablist" aria-label="Library views">
        {(['sources', 'players', 'exports'] as const).map((key) => (
          <button
            type="button"
            role="tab"
            aria-selected={tab === key}
            className={tab === key ? 'is-active' : ''}
            key={key}
            onClick={() => { setTab(key); setQuery(''); setError(null) }}
          >{tabLabel(key)}</button>
        ))}
      </div>
      <label className="library-search">
        <span className="sr-only">Search {tab}</span>
        <input
          type="search"
          value={query}
          placeholder={`Search ${tab}`}
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>
      {error && <p className="inline-error">{error}</p>}

      <div className="library-list" role="tabpanel">
        {tab === 'sources' && sources.map((video) => (
          <article className="library-video" key={video.videoId}>
            <div className="library-video-row">
              <div className="library-thumbnail" aria-hidden="true" />
              <div className="library-video-copy">
                {sourceRenaming === video.videoId ? (
                  <div className="library-rename">
                    <input aria-label="Source name" maxLength={80} value={sourceName} onChange={(event) => setSourceName(event.target.value)} />
                    <button type="button" disabled={busy || !sourceName.trim()} onClick={() => void saveSourceName(video)}>Save</button>
                    <button type="button" disabled={busy} onClick={() => setSourceRenaming(null)}>Cancel</button>
                  </div>
                ) : <strong title={video.name}>{video.name}</strong>}
                <span>{video.sourceKind === 'upload' ? 'Uploaded copy' : 'Registered path'} · {video.tracks.length} player{video.tracks.length === 1 ? '' : 's'}</span>
                <span>{formatBytes(video.size)} · {formatDate(video.openedAt)}</span>
              </div>
              <button type="button" disabled={busy || openingDisabled || !video.sourceExists} onClick={() => onOpenVideo(video)}>Open</button>
            </div>
            <div className="library-actions library-source-actions">
              <button type="button" disabled={busy} onClick={() => { setSourceRenaming(video.videoId); setSourceName(video.name) }}>Rename</button>
              <button type="button" className="danger" disabled={busy} onClick={() => {
                if (window.confirm(`Delete ${video.name} and its saved players/exports?`)) {
                  void run(() => deleteLibraryVideo(video.videoId))
                }
              }}>Delete source</button>
            </div>
          </article>
        ))}

        {tab === 'players' && players.map(({ video, player }) => (
          <article className="library-video library-player" key={player.jobId}>
            <div className="library-video-row">
              <div className="player-thumbnail" aria-hidden="true" />
              <div className="library-video-copy">
                {playerRenaming === player.jobId ? (
                  <div className="library-rename">
                    <input aria-label="Player name" maxLength={80} value={playerName} onChange={(event) => setPlayerName(event.target.value)} />
                    <button type="button" disabled={busy || !playerName.trim()} onClick={() => void savePlayerName(player)}>Save</button>
                    <button type="button" disabled={busy} onClick={() => setPlayerRenaming(null)}>Cancel</button>
                  </div>
                ) : <strong>{player.name}</strong>}
                <span>{video.name}</span>
                <span>{player.frameCount} frames · {player.lostCount} lost · {formatDate(player.createdAt)}</span>
              </div>
              <button type="button" disabled={busy || openingDisabled || !video.sourceExists} onClick={() => void openPlayer(video, player)}>Open player</button>
            </div>
            <div className="library-actions">
              <button type="button" disabled={busy} onClick={() => { setPlayerRenaming(player.jobId); setPlayerName(player.name) }}>Rename</button>
              <button type="button" className="danger" disabled={busy} onClick={() => {
                if (window.confirm(`Delete ${player.name} and its exports?`)) {
                  void run(() => deleteLibraryTrack(player.jobId))
                }
              }}>Delete</button>
            </div>
          </article>
        ))}

        {tab === 'exports' && exports.map(({ video, item, player }) => (
          <article className="library-video library-export" key={item.exportId}>
            <div className="library-video-row">
              <div className="library-thumbnail export" aria-hidden="true" />
              <div className="library-video-copy">
                <strong>{player?.name ?? 'Unknown player'}</strong>
                <span>{video.name}</span>
                <span>{item.params.outWidth ?? '?'} × {item.params.outHeight ?? '?'} · {formatZoom(item.params.zoom)} · {formatBytes(item.size)} · {formatDate(item.createdAt)}</span>
              </div>
              {item.sourceExists && <a href={exportDownloadUrl(item.exportId)} download>Download</a>}
            </div>
            <button type="button" className="library-delete danger" disabled={busy} onClick={() => {
              if (window.confirm('Delete this export?')) void run(() => deleteLibraryExport(item.exportId))
            }}>Delete export</button>
          </article>
        ))}

        {((tab === 'sources' && sources.length === 0)
          || (tab === 'players' && players.length === 0)
          || (tab === 'exports' && exports.length === 0)) && (
          <p className="empty-copy">No {tab} match your search.</p>
        )}
      </div>
    </section>
  )
}

function tabLabel(tab: LibraryTab): string {
  return tab[0].toUpperCase() + tab.slice(1)
}

function formatBytes(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleDateString() : 'Unknown date'
}

function formatZoom(value: unknown): string {
  return typeof value === 'number' ? `${value.toFixed(1)}×` : 'Unknown zoom'
}
