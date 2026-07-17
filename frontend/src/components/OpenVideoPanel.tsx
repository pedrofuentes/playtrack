import { type ChangeEvent, type FormEvent, useState } from 'react'

interface OpenVideoPanelProps {
  disabled: boolean
  variant?: 'empty' | 'drawer'
  onUpload: (file: File) => Promise<void>
  onOpenPath: (path: string) => Promise<void>
}

export function OpenVideoPanel({
  disabled,
  variant = 'empty',
  onUpload,
  onOpenPath,
}: OpenVideoPanelProps) {
  const [path, setPath] = useState('')
  const [busy, setBusy] = useState<'upload' | 'path' | null>(null)
  const unavailable = disabled || busy !== null

  const submitPath = async (event: FormEvent) => {
    event.preventDefault()
    const value = path.trim()
    if (!value || unavailable) return
    setBusy('path')
    try {
      await onOpenPath(value)
    } finally {
      setBusy(null)
    }
  }

  const chooseFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const input = event.currentTarget
    const file = input.files?.[0]
    if (!file || unavailable) return
    setBusy('upload')
    try {
      await onUpload(file)
    } finally {
      setBusy(null)
      input.value = ''
    }
  }

  return (
    <section className={`open-video-panel ${variant}`}>
      <p className="label">Open video</p>
      <label className="file-upload">
        <span>Upload from this computer</span>
        <input
          type="file"
          accept="video/mp4,video/*"
          disabled={unavailable}
          onChange={(event) => void chooseFile(event)}
        />
      </label>
      {variant === 'empty' && <div className="panel-divider"><span>or</span></div>}
      {variant === 'drawer' ? (
        <details className="open-path-options">
          <summary>More options</summary>
          <PathForm
            path={path}
            unavailable={unavailable}
            onPathChange={setPath}
            onSubmit={submitPath}
          />
        </details>
      ) : (
        <PathForm
          path={path}
          unavailable={unavailable}
          onPathChange={setPath}
          onSubmit={submitPath}
        />
      )}
      {busy && (
        <p className="hint" role="status">
          {busy === 'upload' ? 'Uploading…' : 'Opening…'}
        </p>
      )}
    </section>
  )
}

interface PathFormProps {
  path: string
  unavailable: boolean
  onPathChange: (path: string) => void
  onSubmit: (event: FormEvent) => Promise<void>
}

function PathForm({ path, unavailable, onPathChange, onSubmit }: PathFormProps) {
  return (
    <form onSubmit={(event) => void onSubmit(event)}>
      <label htmlFor="server-video-path">Path on the server</label>
      <input
        id="server-video-path"
        type="text"
        value={path}
        disabled={unavailable}
        placeholder="examples/example.mp4"
        onChange={(event) => onPathChange(event.target.value)}
      />
      <button type="submit" disabled={unavailable || !path.trim()}>
        Open server path
      </button>
    </form>
  )
}
