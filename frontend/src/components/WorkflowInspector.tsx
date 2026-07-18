import { type FormEvent, type ReactNode, useEffect, useState } from 'react'

import type {
  ClickSelection,
  LocateCandidate,
  TrackJobUpdate,
  VideoMetadata,
} from '../api'
import type { TrackHealthSummary } from '../trackHealth'
import type { WorkspaceStage } from '../workflow'

interface WorkflowInspectorProps {
  stage: WorkspaceStage
  video: VideoMetadata
  currentFrame: number
  selection: ClickSelection | null
  selectionKind: 'click' | 'text'
  selectionLoading: boolean
  selectionError: string | null
  candidates: readonly LocateCandidate[]
  playerName: string
  textSelectionEnabled: boolean
  trackJob: TrackJobUpdate | null
  trackMessage: string | null
  trackError: string | null
  trackStarting: boolean
  selectionLocked: boolean
  trackStartedAt: number | null
  trackFrameCount: number
  health: TrackHealthSummary | null
  onTextSelect: (prompt: string) => void
  onPlayerNameChange: (name: string) => void
  onTrack: () => void
  onCancelTrack: () => void
  onRetryTrack: () => void
  onResetSelection: () => void
  onBeginFraming: () => void
  onSeek: (frameIdx: number) => void
  exportPanel: ReactNode
}

export function WorkflowInspector(props: WorkflowInspectorProps) {
  const { stage } = props
  return (
    <section className={`workflow-inspector stage-${stage}`} aria-label="Player tracking workflow">
      <header className="inspector-header">
        <div>
          <p className="section-label">Virtual camera</p>
          <h2>{stageTitle(stage)}</h2>
        </div>
        <span className="frame-readout">Frame {props.currentFrame}</span>
      </header>
      <div className="stage-marker" aria-label={`Current stage: ${stageTitle(stage)}`}>
        <span className={markerClass(stage, 'select')} />
        <span className={markerClass(stage, 'track')} />
        <span className={markerClass(stage, 'export')} />
      </div>
      {stage === 'select' && <SelectionInspector {...props} />}
      {stage === 'track' && <TrackingInspector {...props} />}
      {stage === 'review' && <ReviewInspector {...props} />}
      {stage === 'export' && props.exportPanel}
    </section>
  )
}

function SelectionInspector({
  selection,
  selectionKind,
  selectionLoading,
  selectionError,
  candidates,
  textSelectionEnabled,
  onTextSelect,
  playerName,
  onPlayerNameChange,
  onTrack,
  onResetSelection,
  trackStarting,
  selectionLocked,
}: WorkflowInspectorProps) {
  const [prompt, setPrompt] = useState('')
  const [method, setMethod] = useState<'click' | 'describe'>('click')
  const submitPrompt = (event: FormEvent) => {
    event.preventDefault()
    if (!selectionLocked && !trackStarting && prompt.trim()) onTextSelect(prompt)
  }

  return (
    <div className="inspector-body">
      {textSelectionEnabled && (
        <div className="selection-methods" role="group" aria-label="Selection method">
          <button
            type="button"
            data-method="click"
            className={method === 'click' ? 'is-active' : ''}
            aria-pressed={method === 'click'}
            disabled={selectionLocked || trackStarting}
            onClick={() => setMethod('click')}
          >Click</button>
          <button
            type="button"
            data-method="describe"
            className={method === 'describe' ? 'is-active' : ''}
            aria-pressed={method === 'describe'}
            disabled={selectionLocked || trackStarting}
            onClick={() => setMethod('describe')}
          >Describe</button>
        </div>
      )}
      {!selection && method === 'click' && (
        <div className="inspector-callout">
          <p className="section-label">Choose target</p>
          <h3>Click a player</h3>
          <p>Scrub to a clear frame, zoom if needed, then click the player in the video.</p>
        </div>
      )}
      {textSelectionEnabled && !selection && method === 'describe' && (
        <form className="text-selection-form" onSubmit={submitPrompt}>
          <label htmlFor="player-description">Describe a player</label>
          <div>
            <input
              id="player-description"
              value={prompt}
              maxLength={500}
              disabled={selectionLocked || trackStarting}
              placeholder="the player in the white jersey"
              onChange={(event) => setPrompt(event.target.value)}
            />
            <button
              type="submit"
              className="secondary"
              disabled={selectionLocked || trackStarting || selectionLoading || !prompt.trim()}
            >
              Find
            </button>
          </div>
        </form>
      )}
      {selectionLoading && <p className="operation-status" role="status">Finding player…</p>}
      {candidates.length > 0 && (
        <p className="operation-status">{candidates.length} candidate{candidates.length === 1 ? '' : 's'} found. Click a numbered box to confirm.</p>
      )}
      {selectionError && <p className="inline-error">{selectionError}</p>}
      {selection && (
        <div className="selected-player-card">
          <div className="player-thumbnail" aria-hidden="true" />
          <div>
            <strong>Player selected</strong>
            <span>{Math.round(selection.score * 100)}% confidence · {selectionKind === 'click' ? 'Click mask' : 'Description match'}</span>
          </div>
        </div>
      )}
      {selection && (
        <>
          <label className="player-name-field">
            Name this player <span>Optional</span>
            <input
              type="text"
              maxLength={80}
              value={playerName}
              disabled={selectionLocked || trackStarting}
              placeholder="Player 1"
              onChange={(event) => onPlayerNameChange(event.target.value)}
            />
          </label>
          <button type="button" className="primary-action" disabled={selectionLocked || trackStarting} onClick={onTrack}>Track player</button>
          <button type="button" className="secondary-action" disabled={selectionLocked || trackStarting} onClick={onResetSelection}>Choose a different player</button>
        </>
      )}
    </div>
  )
}

function TrackingInspector({
  trackFrameCount,
  trackJob,
  trackMessage,
  trackError,
  trackStartedAt,
  onCancelTrack,
  onRetryTrack,
}: WorkflowInspectorProps) {
  const active = trackJob?.state === 'queued' || trackJob?.state === 'running'
  const elapsed = useElapsedSeconds(trackStartedAt, active)
  const progress = trackJob?.progress ?? 0
  const processed = Math.min(trackFrameCount, Math.round(progress * trackFrameCount))

  return (
    <div className="inspector-body">
      <p className="section-label">SAM 2 propagation</p>
      <h3>{trackJob?.state === 'failed' || trackJob?.state === 'canceled' ? 'Tracking stopped' : `${processed} of ${trackFrameCount} frames`}</h3>
      <div className="job-progress-copy">
        <strong>{Math.round(progress * 100)}%</strong>
        {elapsed !== null && <span>{formatElapsed(elapsed)} elapsed</span>}
      </div>
      <progress max={1} value={progress} aria-label="Tracking progress" />
      {active && <button type="button" className="secondary-action" onClick={onCancelTrack}>Cancel tracking</button>}
      {trackMessage && !trackError && <p className="operation-status">{trackMessage}</p>}
      {trackError && (
        <div className="error-card">
          <strong>{trackError}</strong>
          <p>Your player selection and received frames are still available.</p>
          <button type="button" className="primary-action" onClick={onRetryTrack}>Retry tracking</button>
        </div>
      )}
    </div>
  )
}

function ReviewInspector({ health, playerName, onBeginFraming, onSeek }: WorkflowInspectorProps) {
  const coverage = Math.round((health?.coverage ?? 0) * 100)
  const lostCount = health?.lostCount ?? 0
  return (
    <div className="inspector-body">
      <p className="section-label">Track health</p>
      <h3>{playerName || 'Player'} is ready</h3>
      <div className="review-stats">
        <div><strong>{coverage}%</strong><span>Coverage</span></div>
        <div><strong>{lostCount}</strong><span>Lost frames</span></div>
      </div>
      {lostCount > 0 ? (
        <div className="review-ranges">
          <p>{lostCount} lost frame{lostCount === 1 ? '' : 's'} need review.</p>
          {health?.lostRanges.map((range) => (
            <button
              type="button"
              className="review-range"
              key={`${range.startFrame}:${range.endFrame}`}
              onClick={() => onSeek(range.startFrame)}
            >
              {range.startFrame === range.endFrame
                ? `Frame ${range.startFrame}`
                : `Frames ${range.startFrame}–${range.endFrame}`}
              <span>Jump to frame →</span>
            </button>
          ))}
        </div>
      ) : <p className="healthy-copy">No lost frames detected.</p>}
      <button type="button" className="primary-action" onClick={onBeginFraming}>Set framing</button>
    </div>
  )
}

function useElapsedSeconds(startedAt: number | null, active: boolean): number | null {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active || startedAt === null) return
    setNow(Date.now())
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [active, startedAt])
  return startedAt === null ? null : Math.max(0, Math.floor((now - startedAt) / 1000))
}

function formatElapsed(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds % 60
  return `${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`
}

function stageTitle(stage: WorkspaceStage): string {
  if (stage === 'select') return 'Select player'
  if (stage === 'track') return 'Tracking'
  if (stage === 'review') return 'Review track'
  return 'Output framing'
}

function markerClass(current: WorkspaceStage, marker: 'select' | 'track' | 'export'): string {
  const order: WorkspaceStage[] = ['select', 'track', 'review', 'export']
  const markerIndex = marker === 'export' ? 3 : order.indexOf(marker)
  const currentIndex = order.indexOf(current)
  return markerIndex < currentIndex ? 'is-complete' : markerIndex === currentIndex || (current === 'review' && marker === 'track') ? 'is-current' : ''
}
