import {
  type ChangeEvent,
  type ReactNode,
  useEffect,
  useRef,
} from 'react'

export type WorkspaceSurface = 'editor' | 'library' | 'jobs' | 'settings'

interface WorkspaceShellProps {
  surface: WorkspaceSurface
  videoName: string | null
  videoMeta: string | null
  saved: boolean
  openingDisabled: boolean
  onSurfaceChange: (surface: WorkspaceSurface) => void
  onOpenUpload: (file: File) => Promise<void>
  topAction?: ReactNode
  canvas: ReactNode
  inspector: ReactNode
  timeline: ReactNode
  library: ReactNode
  jobs: ReactNode
  settings: ReactNode
}

const SURFACES: Array<{ key: WorkspaceSurface; icon: string; label: string }> = [
  { key: 'editor', icon: '▣', label: 'Editor' },
  { key: 'library', icon: '▤', label: 'Library' },
  { key: 'jobs', icon: '◷', label: 'Jobs' },
  { key: 'settings', icon: '⚙', label: 'Settings' },
]

export function WorkspaceShell({
  surface,
  videoName,
  videoMeta,
  saved,
  openingDisabled,
  onSurfaceChange,
  onOpenUpload,
  topAction,
  canvas,
  inspector,
  timeline,
  library,
  jobs,
  settings,
}: WorkspaceShellProps) {
  const lastTrigger = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    if (surface === 'editor') return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onSurfaceChange('editor')
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onSurfaceChange, surface])

  useEffect(() => {
    if (surface === 'editor') lastTrigger.current?.focus()
  }, [surface])

  const chooseSurface = (next: WorkspaceSurface, trigger: HTMLButtonElement) => {
    lastTrigger.current = trigger
    onSurfaceChange(next)
  }

  const chooseFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const input = event.currentTarget
    const file = input.files?.[0]
    if (!file || openingDisabled) return
    try {
      await onOpenUpload(file)
    } finally {
      input.value = ''
    }
  }

  const drawer = surface === 'library'
    ? library
    : surface === 'jobs'
      ? jobs
      : surface === 'settings'
        ? settings
        : null

  return (
    <main className="workspace-shell">
      <header className="workspace-topbar">
        <div className="findme-mark" aria-label="FindMe">F</div>
        <div className="active-video">
          <strong>{videoName ?? 'No video open'}</strong>
          {saved && <span className="status-pill">Saved</span>}
          {videoMeta && <span>{videoMeta}</span>}
        </div>
        <div className="topbar-actions">
          <span className="shortcut-hint">Ctrl/⌘ K</span>
          <label className={`button secondary${openingDisabled ? ' is-disabled' : ''}`}>
            Open video
            <input
              className="sr-only"
              type="file"
              accept="video/mp4,video/*"
              disabled={openingDisabled}
              onChange={(event) => void chooseFile(event)}
            />
          </label>
          {topAction}
        </div>
      </header>

      <nav className="activity-rail" aria-label="Editor tools">
        {SURFACES.map((item) => (
          <button
            key={item.key}
            type="button"
            className={surface === item.key ? 'is-active' : ''}
            aria-current={surface === item.key ? 'page' : undefined}
            title={item.label}
            onClick={(event) => chooseSurface(item.key, event.currentTarget)}
          >
            <span aria-hidden="true">{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}
      </nav>

      <section className="canvas-region" aria-label="Video editor">{canvas}</section>
      <aside className="inspector-region">{inspector}</aside>
      <div className="timeline-region">{timeline}</div>

      {drawer && (
        <aside className="workspace-drawer" role="dialog" aria-modal="false" aria-label={surface}>
          <header>
            <strong>{capitalize(surface)}</strong>
            <button type="button" aria-label={`Close ${surface}`} onClick={() => onSurfaceChange('editor')}>×</button>
          </header>
          <div className="drawer-content">{drawer}</div>
        </aside>
      )}
    </main>
  )
}

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1)
}
