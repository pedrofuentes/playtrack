import { useMemo, useRef, useState } from 'react'

import {
  exportDownloadUrl,
  type LibraryVideo,
  type TrackJobUpdate,
  videoFileUrl,
} from './api'
import { type ExportPanelHandle, ExportPanel } from './components/ExportPanel'
import { LibraryPanel } from './components/LibraryPanel'
import { OpenVideoPanel } from './components/OpenVideoPanel'
import { SettingsPanel } from './components/SettingsPanel'
import { TrackTimeline } from './components/TrackTimeline'
import { type VideoStageHandle, VideoStage } from './components/VideoStage'
import { WorkflowInspector } from './components/WorkflowInspector'
import { type WorkspaceSurface, WorkspaceShell } from './components/WorkspaceShell'
import { useWorkspace } from './hooks/useWorkspace'
import { useWorkspaceShortcuts } from './hooks/useWorkspaceShortcuts'
import { summarizeTrack } from './trackHealth'

const EXAMPLE_PATH = 'examples/example.mp4'

export default function App() {
  const workspace = useWorkspace()
  const [surface, setSurface] = useState<WorkspaceSurface>('editor')
  const videoStageRef = useRef<VideoStageHandle>(null)
  const exportPanelRef = useRef<ExportPanelHandle>(null)

  const health = useMemo(() => (
    workspace.video && workspace.trackJob?.state === 'completed'
      ? summarizeTrack(workspace.trackJob.track, workspace.video.nbFrames)
      : null
  ), [workspace.trackJob, workspace.video])

  const primaryAction = () => {
    if (workspace.stage === 'select' && workspace.selection) void workspace.startTrack()
    else if (workspace.stage === 'track' && workspace.trackJob?.state === 'failed') void workspace.retryTrack()
    else if (workspace.stage === 'review') workspace.beginFraming()
    else if (workspace.stage === 'export') exportPanelRef.current?.triggerExport()
  }

  useWorkspaceShortcuts({
    togglePlayback: () => videoStageRef.current?.togglePlayback(),
    stepFrames: (delta) => videoStageRef.current?.stepFrames(delta),
    primaryAction,
    openLibrary: () => setSurface('library'),
    closeSurface: () => setSurface('editor'),
  })

  const seekToFrame = (frameIdx: number) => videoStageRef.current?.seekToFrame(frameIdx)
  const exportPanel = workspace.video && workspace.trackJob?.state === 'completed' ? (
    <ExportPanel
      key={`${workspace.video.videoId}:${workspace.trackJob.jobId}`}
      ref={exportPanelRef}
      videoId={workspace.video.videoId}
      trackJobId={workspace.trackJob.jobId}
      onPlanChange={workspace.setCropWindows}
      onJobChange={workspace.setExportJob}
      onLibraryChange={workspace.refreshLibrary}
    />
  ) : null

  const canvas = workspace.video ? (
    <VideoStage
      ref={videoStageRef}
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
    <EmptyWorkspace
      loading={workspace.loading}
      loadingLabel={workspace.loadingLabel}
      error={workspace.openError}
      onUpload={workspace.openUpload}
      onOpenPath={workspace.openPath}
    />
  )

  const inspector = workspace.video ? (
    <WorkflowInspector
      stage={workspace.stage}
      video={workspace.video}
      currentFrame={workspace.currentFrame}
      selection={workspace.selection}
      selectionKind={workspace.selectionKind}
      selectionLoading={workspace.selectionLoading}
      selectionError={workspace.selectionError}
      candidates={workspace.candidates}
      textSelectionEnabled={workspace.features.textSelection.enabled}
      trackJob={workspace.trackJob}
      trackMessage={workspace.trackMessage}
      trackError={workspace.trackError}
      trackStartedAt={workspace.trackStartedAt}
      health={health}
      onTextSelect={workspace.selectByDescription}
      onTrack={() => void workspace.startTrack()}
      onRetryTrack={() => void workspace.retryTrack()}
      onResetSelection={workspace.resetSelection}
      onBeginFraming={workspace.beginFraming}
      onSeek={seekToFrame}
      exportPanel={exportPanel}
    />
  ) : (
    <section className="empty-inspector">
      <p className="section-label">Get started</p>
      <h2>Open a video</h2>
      <p>Choose panoramic sports footage to begin selecting and tracking a player.</p>
    </section>
  )

  const timeline = workspace.video ? (
    <TrackTimeline
      currentFrame={workspace.currentFrame}
      frameCount={workspace.video.nbFrames}
      fps={workspace.video.fps}
      jobProgress={workspace.trackJob?.progress ?? null}
      health={health}
      onSeek={seekToFrame}
    />
  ) : <div className="empty-timeline">Space to play · ← → to step frames · ⌘K to open Library</div>

  const topAction = workspace.exportJob?.state === 'completed' ? (
    <a className="button primary" href={exportDownloadUrl(workspace.exportJob.jobId)} download>
      Download MP4
    </a>
  ) : null

  return (
    <WorkspaceShell
      surface={surface}
      videoName={workspace.videoName}
      videoMeta={workspace.video ? formatVideoMeta(workspace.video.width, workspace.video.height, workspace.video.duration) : null}
      saved={Boolean(workspace.video)}
      openingDisabled={workspace.loading || workspace.videoSwitchLocked}
      onSurfaceChange={setSurface}
      onOpenUpload={workspace.openUpload}
      topAction={topAction}
      canvas={canvas}
      inspector={inspector}
      timeline={timeline}
      library={(
        <div className="library-drawer-content">
          <OpenVideoPanel
            variant="drawer"
            disabled={workspace.loading || workspace.videoSwitchLocked}
            onUpload={async (file) => {
              await workspace.openUpload(file)
              setSurface('editor')
            }}
            onOpenPath={async (path) => {
              await workspace.openPath(path)
              setSurface('editor')
            }}
          />
          <LibraryPanel
            library={workspace.library}
            openingDisabled={workspace.videoSwitchLocked}
            onOpenVideo={(saved) => {
              void workspace.openLibraryVideo(saved)
              setSurface('editor')
            }}
            onReExport={(saved, jobId) => {
              void workspace.reExportLibraryTrack(saved, jobId)
              setSurface('editor')
            }}
            onRefresh={workspace.refreshLibrary}
          />
        </div>
      )}
      jobs={<JobPanel trackJob={workspace.trackJob} exportJob={workspace.exportJob} frameCount={workspace.video?.nbFrames ?? 0} />}
      settings={<SettingsPanel cacheBytes={workspace.library.cacheBytes} onClearFrameCaches={workspace.clearCaches} />}
    />
  )
}

interface EmptyWorkspaceProps {
  loading: boolean
  loadingLabel: string
  error: string | null
  onUpload: (file: File) => Promise<void>
  onOpenPath: (path: string) => Promise<void>
}

function EmptyWorkspace({ loading, loadingLabel, error, onUpload, onOpenPath }: EmptyWorkspaceProps) {
  if (loading) return <div className="empty-workspace"><div className="activity-spinner" /><p>{loadingLabel}</p></div>
  return (
    <div className="empty-workspace">
      <div className="empty-symbol" aria-hidden="true">＋</div>
      <h1>{error ? 'Could not open video' : 'Open panoramic footage'}</h1>
      <p>{error ?? 'Drop in a sports video and turn it into a player-following virtual camera.'}</p>
      <OpenVideoPanel disabled={false} variant="empty" onUpload={onUpload} onOpenPath={onOpenPath} />
      {error && <button type="button" className="secondary-action" onClick={() => void onOpenPath(EXAMPLE_PATH)}>Retry example</button>}
    </div>
  )
}

function JobPanel({ trackJob, exportJob, frameCount }: {
  trackJob: TrackJobUpdate | null
  exportJob: TrackJobUpdate | null
  frameCount: number
}) {
  const job = exportJob ?? trackJob
  if (!job) return <p className="empty-copy">No tracking or export job yet.</p>
  const title = exportJob ? 'Exporting video' : 'Tracking player'
  return (
    <section className="job-panel">
      <div className="job-heading"><h3>{title}</h3><span className={`status-pill state-${job.state}`}>{job.state}</span></div>
      <strong className="job-percentage">{Math.round(job.progress * 100)}%</strong>
      <progress max={1} value={job.progress} />
      <p>{job.message}</p>
      {!exportJob && frameCount > 0 && <span>{Math.round(job.progress * frameCount)} / {frameCount} frames</span>}
    </section>
  )
}

export function libraryVideoName(video: Pick<LibraryVideo, 'name'>): string {
  return video.name
}

function formatVideoMeta(width: number, height: number, duration: number): string {
  return `${width} × ${height} · ${formatDuration(duration)}`
}

function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
  const remainder = Math.round(seconds % 60)
  return minutes > 0 ? `${minutes}:${String(remainder).padStart(2, '0')}` : `${remainder} sec`
}
