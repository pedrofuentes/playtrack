import { useState } from 'react'

interface SettingsPanelProps {
  cacheBytes: number
  onClearFrameCaches: () => Promise<void>
}

export function SettingsPanel({ cacheBytes, onClearFrameCaches }: SettingsPanelProps) {
  const [busy, setBusy] = useState(false)
  const clear = async () => {
    if (!window.confirm('Clear extracted frame caches? Source videos, tracks, and exports are kept.')) return
    setBusy(true)
    try {
      await onClearFrameCaches()
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="settings-panel">
      <p className="section-label">Storage</p>
      <div className="settings-row">
        <div>
          <strong>Frame cache</strong>
          <p>Temporary extracted frames used by tracking.</p>
        </div>
        <span>{formatBytes(cacheBytes)}</span>
      </div>
      <button type="button" className="secondary danger" disabled={busy} onClick={() => void clear()}>
        {busy ? 'Clearing…' : 'Clear frame cache'}
      </button>
    </section>
  )
}

function formatBytes(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
