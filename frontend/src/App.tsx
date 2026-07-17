import { useState } from 'react'

import { type LibraryVideo, videoFileUrl } from './api'
import { ExportPanel } from './components/ExportPanel'
import { LibraryPanel } from './components/LibraryPanel'
import { OpenVideoPanel } from './components/OpenVideoPanel'
import { VideoStage } from './components/VideoStage'
import { useWorkspace } from './hooks/useWorkspace'

const EXAMPLE_PATH = 'examples/example.mp4'

export default function App() {
  const workspace = useWorkspace()
  const [textPrompt, setTextPrompt] = useState('')
  const workflowStep = workspace.stage === 'select' ? 1 : workspace.stage === 'track' ? 2 : 3
  const exportReady = Boolean(workspace.video && workspace.trackJob?.state === 'completed')

  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <p className="eyebrow">Panoramic player tracking</p>
          <h1>FindMe</h1>
        </div>
        <p className="intro">
          Open any sports video, zoom in to identify a player, then track and export them.
        </p>
      </header>

      <section className="workspace" aria-live="polite">
        {workspace.video ? (
          <VideoStage
            src={videoFileUrl(workspace.video.videoId)}
            sourceWidth={workspace.video.width}
            sourceHeight={workspace.video.height}
            fps={workspace.video.fps}
            frameCount={workspace.video.nbFrames}
            selection={workspace.selection}
            track={workspace.trackJob?.track ?? []}
            cropWindows={workspace.cropWindows}
            candidates={workspace.candidates}
            onSourceClick={workspace.selectAt}
            onCandidateConfirm={workspace.confirmCandidate}
            onFrameChange={workspace.setCurrentFrame}
          />
        ) : (
          <div className={`status-panel${workspace.openError ? ' error-panel' : ''}`}>
            {workspace.loading ? <p>{workspace.loadingLabel}</p> : workspace.openError ? (
              <>
                <p>{workspace.openError}</p>
                <button type="button" onClick={() => void workspace.openPath(EXAMPLE_PATH)}>
                  Retry example
                </button>
              </>
            ) : <p>Choose a video to begin.</p>}
          </div>
        )}
        <aside className="details-panel">
          <OpenVideoPanel
            disabled={workspace.loading || workspace.videoSwitchLocked}
            onUpload={workspace.openUpload}
            onOpenPath={workspace.openPath}
          />
          <LibraryPanel
            library={workspace.library}
            onOpenVideo={(saved) => { void workspace.openLibraryVideo(saved) }}
            onReExport={(saved, jobId) => { void workspace.reExportLibraryTrack(saved, jobId) }}
            onRefresh={workspace.refreshLibrary}
          />
          <nav className="workflow-steps" aria-label="FindMe workflow">
            <ol>
              {(['Select player', 'Track', 'Export'] as const).map((label, index) => {
                const step = index + 1
                return (
                  <li
                    key={label}
                    className={step === workflowStep ? 'is-current' : step < workflowStep ? 'is-complete' : ''}
                    aria-current={step === workflowStep ? 'step' : undefined}
                  >
                    <span>{step}</span>{label}
                  </li>
                )
              })}
            </ol>
          </nav>
          {workspace.video && (
            <>
              <div className="video-name">
                <p className="label">Video</p>
                <p className="value" title={workspace.videoName ?? undefined}>{workspace.videoName}</p>
              </div>
              <div>
                <p className="label">Source</p>
                <p className="value">{workspace.video.width} × {workspace.video.height}</p>
              </div>
              <div>
                <p className="label">Frame rate</p>
                <p className="value">{formatNumber(workspace.video.fps)} fps</p>
              </div>
              <div>
                <p className="label">Frames</p>
                <p className="value">{workspace.video.nbFrames.toLocaleString()}</p>
              </div>
              <div>
                <p className="label">Duration</p>
                <p className="value">{formatNumber(workspace.video.duration)} s</p>
              </div>
              <div className="selection-readout">
                <p className="label">Player selection</p>
                {workspace.features.textSelection.enabled && (
                  <form
                    className="text-selection-form"
                    onSubmit={(event) => {
                      event.preventDefault()
                      workspace.selectByDescription(textPrompt)
                    }}
                  >
                    <label htmlFor="player-prompt">Find by description</label>
                    <div>
                      <input
                        id="player-prompt"
                        type="text"
                        value={textPrompt}
                        maxLength={500}
                        placeholder="the player in the white jersey"
                        onChange={(event) => setTextPrompt(event.target.value)}
                      />
                      <button
                        type="submit"
                        disabled={workspace.selectionLoading || !textPrompt.trim()}
                      >
                        Find
                      </button>
                    </div>
                  </form>
                )}
                {workspace.selectionLoading && <p className="value">Finding player…</p>}
                {workspace.selectionError && <p className="selection-error">{workspace.selectionError}</p>}
                {workspace.candidates.length > 0 && (
                  <p className="hint">
                    {workspace.candidates.length} candidate{workspace.candidates.length === 1 ? '' : 's'} found.
                    Click a pink box in the video to confirm.
                  </p>
                )}
                {workspace.selection && (
                  <>
                    <p className="value selection-score">
                      {workspace.selectionKind === 'click' ? 'Mask' : 'Candidate'} score{' '}
                      {(workspace.selection.score * 100).toFixed(1)}%
                    </p>
                    <button
                      type="button"
                      disabled={workspace.trackStarting || workspace.videoSwitchLocked}
                      onClick={() => void workspace.startTrack()}
                    >
                      {workspace.trackStarting || workspace.trackJob?.state === 'running'
                        ? 'Tracking…'
                        : 'Track this player'}
                    </button>
                  </>
                )}
                {!workspace.selection && !workspace.selectionLoading && !workspace.selectionError && (
                  <p className="hint">
                    Click a player for a SAM 2 mask
                    {workspace.features.textSelection.enabled ? ', or describe one above.' : '.'}
                  </p>
                )}
                {workspace.trackMessage && <p className="hint track-message">{workspace.trackMessage}</p>}
                {workspace.trackJob && (
                  <progress
                    className="tracking-progress"
                    max={1}
                    value={workspace.trackJob.progress}
                    aria-label="Tracking progress"
                  />
                )}
                {workspace.trackError && <p className="selection-error">{workspace.trackError}</p>}
              </div>
            </>
          )}
          <ExportPanel
            key={`${workspace.video?.videoId ?? 'none'}:${workspace.trackJob?.jobId ?? 'none'}`}
            videoId={workspace.video?.videoId ?? ''}
            trackJobId={workspace.trackJob?.jobId ?? ''}
            disabled={!exportReady}
            onPlanChange={workspace.setCropWindows}
          />
        </aside>
      </section>
    </main>
  )
}

export function libraryVideoName(video: Pick<LibraryVideo, 'name'>): string {
  return video.name
}

function formatNumber(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(2)
}
