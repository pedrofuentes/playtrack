import {
  type ChangeEvent,
  type DragEvent,
  type FormEvent,
  useId,
  useState,
} from 'react'

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
  const [dragging, setDragging] = useState(false)
  const pathInputId = `server-video-path-${useId()}`
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

  const openFile = async (file: File | undefined) => {
    if (!file || unavailable) return
    setBusy('upload')
    try {
      await onUpload(file)
    } finally {
      setBusy(null)
    }
  }

  const chooseFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const input = event.currentTarget
    try {
      await openFile(input.files?.[0])
    } finally {
      input.value = ''
    }
  }

  const dropFile = async (event: DragEvent<HTMLElement>) => {
    event.preventDefault()
    setDragging(false)
    await openFile(event.dataTransfer.files?.[0])
  }

  return (
    <section
      className={`open-video-panel ${variant}${dragging ? ' is-dragging' : ''}`}
      onDragOver={(event) => {
        event.preventDefault()
        if (!unavailable) setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => void dropFile(event)}
    >
      <p className="label">Open video</p>
      <label className="file-upload">
        <span>{variant === 'empty' ? 'Drop a video here or browse this computer' : 'Upload from this computer'}</span>
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
            inputId={pathInputId}
            path={path}
            unavailable={unavailable}
            onPathChange={setPath}
            onSubmit={submitPath}
          />
        </details>
      ) : (
        <PathForm
          inputId={pathInputId}
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
  inputId: string
  path: string
  unavailable: boolean
  onPathChange: (path: string) => void
  onSubmit: (event: FormEvent) => Promise<void>
}

function PathForm({ inputId, path, unavailable, onPathChange, onSubmit }: PathFormProps) {
  return (
    <form onSubmit={(event) => void onSubmit(event)}>
      <label htmlFor={inputId}>Path on the server</label>
      <input
        id={inputId}
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
