# FindMe UI/UX Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace FindMe's dense single-sidebar page with the approved pro-editor workspace while preserving the working video, tracking, crop, export, and persistence behavior.

**Architecture:** Keep the backend and `api.ts` contracts unchanged. Move async workflow state into `useWorkspace`, keep video geometry in `VideoStage`, derive track health in a pure module, and compose the UI from a stable shell, contextual inspector, timeline, and on-demand drawers. `App.tsx` becomes the composition root and owns only surface navigation plus refs that connect keyboard/timeline actions to the video and export controls.

**Tech Stack:** React 19, TypeScript 6, Vite 6, Vitest 3, existing CSS and browser media/canvas APIs. No new runtime or test dependency.

## Global Constraints

- Preserve all existing backend routes, request/response shapes, WebSocket behavior, persistence schemas, and model pipelines.
- Preserve `geometry.ts`, letterbox-aware click mapping, zoom/pan behavior, selection masks, track overlays, and crop overlays.
- Keep one active video; disable video switching while tracking or export is queued/running.
- Text selection is present only when `features.textSelection.enabled` is true.
- Registered path sources must never be represented as deletable media; uploaded-source deletion continues to use the existing backend endpoint safeguards.
- Default export is 1280 × 720; custom dimensions must remain positive even numbers.
- The desktop editor is primary; below 860 px the inspector becomes a bottom sheet, the timeline condenses, and the activity rail becomes bottom navigation.
- Use the existing system sans-serif stack. Use amber for primary action/crop, mint for selected/healthy, orange for review, and soft red for errors/destructive actions; every state also has text or icon labeling.
- Keyboard shortcuts must ignore editable controls: Space play/pause, Left/Right one frame, Enter current primary action, Cmd/Ctrl+K Library, Escape close surface.
- No unmarked test may depend on model weights, network, GPU, or `examples/example.mp4`.

---

## File Structure

**Create:**

- `frontend/src/trackHealth.ts` — pure coverage and contiguous lost-range derivation.
- `frontend/src/trackHealth.test.ts` — pure track-health tests.
- `frontend/src/workflow.ts` — workflow-stage and active-job selectors.
- `frontend/src/workflow.test.ts` — selector tests.
- `frontend/src/hooks/useWorkspace.ts` — video/selection/tracking/library state and async actions currently held by `App.tsx`.
- `frontend/src/hooks/useWorkspaceShortcuts.ts` — guarded global keyboard routing.
- `frontend/src/hooks/useWorkspaceShortcuts.test.tsx` — shortcut behavior in jsdom.
- `frontend/src/components/WorkspaceShell.tsx` — top bar, activity rail, editor regions, and drawer framing.
- `frontend/src/components/WorkspaceShell.test.tsx` — shell semantics and active navigation.
- `frontend/src/components/WorkflowInspector.tsx` — Select, Track, Review, and Export inspector states.
- `frontend/src/components/WorkflowInspector.test.tsx` — state-specific controls and primary actions.
- `frontend/src/components/TrackTimeline.tsx` — playhead, coverage/lost segments, and seek buttons.
- `frontend/src/components/TrackTimeline.test.tsx` — timeline segment rendering and seeking.
- `frontend/src/components/SettingsPanel.tsx` — cache display/clear action.

**Modify:**

- `frontend/src/App.tsx` — replace monolithic markup/state with the shell composition.
- `frontend/src/App.test.ts` — update exported helper expectations and static UI assertions.
- `frontend/src/components/VideoStage.tsx` — expose playback/seek methods and selected-player label.
- `frontend/src/components/VideoStage.interaction.test.tsx` — cover imperative playback/seek methods.
- `frontend/src/components/ExportPanel.tsx` — compact common path, advanced disclosure, status callbacks, imperative export action, and 150 ms preview debounce.
- `frontend/src/components/ExportPanel.test.ts` — update visible/advanced settings and default behavior assertions.
- `frontend/src/components/LibraryPanel.tsx` — convert permanent nested panel to searchable drawer content and remove cache maintenance.
- `frontend/src/components/LibraryPanel.test.ts` — cover filtering, source labels, and locked opening.
- `frontend/src/components/OpenVideoPanel.tsx` — support compact/empty-state presentation and keep upload/path behavior.
- `frontend/src/styles.css` — replace page/sidebar styling with the approved editor visual system and responsive regions.
- `.gitignore` — retain the already-approved `.superpowers/` ignore rule.

---

### Task 1: Pure Workflow and Track-Health Model

**Files:**

- Create: `frontend/src/trackHealth.ts`
- Create: `frontend/src/trackHealth.test.ts`
- Create: `frontend/src/workflow.ts`
- Create: `frontend/src/workflow.test.ts`
- Modify: `frontend/src/App.test.ts`

**Interfaces:**

- Consumes: `TrackFrame`, `TrackJobUpdate`, and `ClickSelection` from `frontend/src/api.ts`.
- Produces: `summarizeTrack(track, frameCount): TrackHealthSummary`, `workspaceStage(selection, trackJob, framing): WorkspaceStage`, and `isJobActive(job): boolean`.

- [ ] **Step 1: Write failing pure tests**

```ts
// trackHealth.test.ts
expect(summarizeTrack([
  frame(0, false), frame(1, true), frame(2, true), frame(3, false),
], 4)).toEqual({
  coveredCount: 2,
  lostCount: 2,
  coverage: 0.5,
  lostRanges: [{ startFrame: 1, endFrame: 2, frameCount: 2 }],
})

// workflow.test.ts
expect(workspaceStage(null, null, false)).toBe('select')
expect(workspaceStage(selection, runningJob, false)).toBe('track')
expect(workspaceStage(null, completedJob, false)).toBe('review')
expect(workspaceStage(selection, completedJob, true)).toBe('export')
expect(isJobActive(runningJob)).toBe(true)
expect(isJobActive(completedJob)).toBe(false)
```

- [ ] **Step 2: Run the tests to verify red**

Run: `cd frontend && npm test -- src/trackHealth.test.ts src/workflow.test.ts`

Expected: FAIL because both modules are missing.

- [ ] **Step 3: Implement the pure modules**

```ts
export interface TrackHealthRange {
  startFrame: number
  endFrame: number
  frameCount: number
}

export interface TrackHealthSummary {
  coveredCount: number
  lostCount: number
  coverage: number
  lostRanges: TrackHealthRange[]
}

export function summarizeTrack(
  track: readonly TrackFrame[],
  frameCount: number,
): TrackHealthSummary

export type WorkspaceStage = 'select' | 'track' | 'review' | 'export'

export function workspaceStage(
  selection: ClickSelection | null,
  trackJob: TrackJobUpdate | null,
  framing: boolean,
): WorkspaceStage

export function isJobActive(job: TrackJobUpdate | null): boolean
```

`summarizeTrack` must count a frame as lost when `frame.lost` is true or
`frame.box` is null, sort by `frameIdx`, merge consecutive lost frame indices,
and compute coverage against the supplied source `frameCount` (zero when the
source frame count is not positive). Frames absent from a partial job are not
classified as lost; they are simply uncovered.

- [ ] **Step 4: Run focused and existing helper tests**

Run: `cd frontend && npm test -- src/trackHealth.test.ts src/workflow.test.ts src/App.test.ts`

Expected: PASS. Update `App.test.ts` to import `workspaceStage` instead of the
removed `currentWorkflowStep` helper.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/trackHealth.ts frontend/src/trackHealth.test.ts frontend/src/workflow.ts frontend/src/workflow.test.ts frontend/src/App.test.ts
git commit -m "Add UI workflow and track health model"
```

---

### Task 2: Controllable Video Stage and Track Timeline

**Files:**

- Create: `frontend/src/components/TrackTimeline.tsx`
- Create: `frontend/src/components/TrackTimeline.test.tsx`
- Modify: `frontend/src/components/VideoStage.tsx`
- Modify: `frontend/src/components/VideoStage.interaction.test.tsx`

**Interfaces:**

- Consumes: `TrackHealthSummary`, `TrackHealthRange`, source FPS/frame count,
  current frame, and tracking progress.
- Produces: `VideoStageHandle` and `TrackTimeline`.

- [ ] **Step 1: Write failing video-handle and timeline tests**

```ts
export interface VideoStageHandle {
  togglePlayback(): void
  seekToFrame(frameIdx: number): void
  stepFrames(delta: number): void
}

render(<TrackTimeline
  currentFrame={20}
  frameCount={100}
  fps={25}
  jobProgress={1}
  health={{ coveredCount: 97, lostCount: 3, coverage: .97,
    lostRanges: [{ startFrame: 40, endFrame: 42, frameCount: 3 }] }}
  onSeek={onSeek}
/>)
expect(markup).toContain('97% coverage')
expect(markup).toContain('Frames 40–42 need review')
```

In the jsdom interaction test, render `VideoStage` with a ref, stub
`HTMLMediaElement.prototype.play`, set `video.currentTime`, call
`ref.current?.seekToFrame(30)`, and expect `currentTime` to equal `1` at 30 fps.

- [ ] **Step 2: Run focused tests to verify red**

Run: `cd frontend && npm test -- src/components/TrackTimeline.test.tsx src/components/VideoStage.interaction.test.tsx`

Expected: FAIL because `TrackTimeline` and `VideoStageHandle` do not exist.

- [ ] **Step 3: Expose imperative media controls**

Convert `VideoStage` to `forwardRef<VideoStageHandle, VideoStageProps>` and use
`useImperativeHandle`. Clamp all seeks to `0..frameCount - 1`. Convert frames to
seconds using `frameIdx / fps`. `togglePlayback` calls `pause()` when playing and
`play()` when paused. Keep every existing pointer, zoom, overlay, and geometry
path unchanged.

Draw a mint `Selected player` tag adjacent to the selected box in
`drawOverlayCanvas`. Add a screen-reader-only live status with the same text so
selection is not communicated only by canvas color.

- [ ] **Step 4: Implement the timeline**

```ts
interface TrackTimelineProps {
  currentFrame: number
  frameCount: number
  fps: number
  jobProgress: number | null
  health: TrackHealthSummary | null
  onSeek: (frameIdx: number) => void
}
```

Render a labeled playhead, a processed-coverage layer from `jobProgress`, and
one `<button>` per lost range. Position with clamped percentage inline styles.
Each range button uses `aria-label="Frames X–Y need review"`, and clicking it
calls `onSeek(startFrame)`. Show current time/frame plus coverage and lost count
in text.

- [ ] **Step 5: Run the focused tests**

Run: `cd frontend && npm test -- src/components/TrackTimeline.test.tsx src/components/VideoStage.interaction.test.tsx src/components/VideoStage.test.ts`

Expected: PASS with all existing zoom/pan/click tests unchanged.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/TrackTimeline.tsx frontend/src/components/TrackTimeline.test.tsx frontend/src/components/VideoStage.tsx frontend/src/components/VideoStage.interaction.test.tsx
git commit -m "Add track timeline and video controls"
```

---

### Task 3: Workspace Controller Hook

**Files:**

- Create: `frontend/src/hooks/useWorkspace.ts`
- Create: `frontend/src/hooks/useWorkspace.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**

- Consumes: all existing video, feature, library, selection, tracking, and job
  API functions currently called in `App.tsx`.
- Produces: `WorkspaceController` with serializable state plus stable action
  callbacks.

- [ ] **Step 1: Write failing controller tests with mocked API functions**

Test that opening a video resets selection/track/crop/framing state, a source
click aborts the previous selection request, a completed track enters `review`,
`beginFraming()` enters `export`, and `videoSwitchLocked` is true for queued or
running track/export state.

```ts
interface WorkspaceController {
  video: VideoMetadata | null
  videoName: string | null
  currentFrame: number
  selection: ClickSelection | null
  selectionKind: 'click' | 'text'
  selectionLoading: boolean
  selectionError: string | null
  candidates: LocateCandidate[]
  features: FeatureFlags
  library: LibraryResponse
  trackJob: TrackJobUpdate | null
  trackMessage: string | null
  trackError: string | null
  trackStartedAt: number | null
  cropWindows: CropWindow[]
  loading: boolean
  loadingLabel: string
  openError: string | null
  framing: boolean
  exportJob: TrackJobUpdate | null
  stage: WorkspaceStage
  videoSwitchLocked: boolean
  openUpload(file: File): Promise<void>
  openPath(path: string): Promise<void>
  openLibraryVideo(video: LibraryVideo): Promise<void>
  reExportLibraryTrack(video: LibraryVideo, jobId: string): Promise<void>
  refreshLibrary(): void
  selectAt(point: Point, frameIdx: number): void
  selectByDescription(prompt: string): void
  confirmCandidate(candidate: LocateCandidate, frameIdx: number): void
  setCurrentFrame(frameIdx: number): void
  startTrack(): Promise<void>
  retryTrack(): Promise<void>
  beginFraming(): void
  setCropWindows(windows: CropWindow[]): void
  setExportJob(job: TrackJobUpdate | null): void
  resetSelection(): void
  clearCaches(): Promise<void>
}
```

- [ ] **Step 2: Run the hook test to verify red**

Run: `cd frontend && npm test -- src/hooks/useWorkspace.test.tsx`

Expected: FAIL because `useWorkspace` is missing.

- [ ] **Step 3: Move existing async state and actions without changing API behavior**

Move the existing request abortion, socket cleanup, example-open attempt,
feature loading, library refresh, upload/path/library opening, selection,
candidate confirmation, tracking, and restored-track logic from `App.tsx` into
`useWorkspace`. Preserve the same default error text and cleanup effects.
`clearCaches` calls the existing cache endpoint and refreshes Library state.

Add `framing`, `exportJob`, `stage`, and `videoSwitchLocked`. Do not clear
received partial frames when a tracking job fails. `retryTrack` reuses the
current video, anchor frame, and selected box. Set `trackStartedAt` to
`Date.now()` immediately before each new tracking request and leave it `null`
for a restored persisted track whose original start time is unavailable.

- [ ] **Step 4: Run hook and API tests**

Run: `cd frontend && npm test -- src/hooks/useWorkspace.test.tsx src/api.test.ts src/workflow.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useWorkspace.ts frontend/src/hooks/useWorkspace.test.tsx frontend/src/App.tsx
git commit -m "Extract the editor workspace controller"
```

---

### Task 4: Stable Editor Shell and Secondary Drawers

**Files:**

- Create: `frontend/src/components/WorkspaceShell.tsx`
- Create: `frontend/src/components/WorkspaceShell.test.tsx`
- Create: `frontend/src/components/SettingsPanel.tsx`
- Modify: `frontend/src/components/LibraryPanel.tsx`
- Modify: `frontend/src/components/LibraryPanel.test.ts`
- Modify: `frontend/src/components/OpenVideoPanel.tsx`

**Interfaces:**

- Consumes: active surface, video identity, job state, library response, and
  existing open/delete/clear callbacks.
- Produces: `WorkspaceShell`, searchable `LibraryPanel`, and `SettingsPanel`.

- [ ] **Step 1: Write failing shell and library tests**

Assert that the shell has a top bar, labeled Editor/Library/Jobs/Settings rail
buttons, a main canvas region, a complementary inspector, and a timeline slot.
Assert that selecting Library renders drawer content and Escape calls
`onCloseSurface`. In the Library test, filter three videos by name and verify
that `openingDisabled` disables only Open/Re-export while Delete/Download remain
governed by their existing availability.

- [ ] **Step 2: Run focused tests to verify red**

Run: `cd frontend && npm test -- src/components/WorkspaceShell.test.tsx src/components/LibraryPanel.test.ts`

Expected: FAIL because `WorkspaceShell` and the new Library props are absent.

- [ ] **Step 3: Implement `WorkspaceShell`**

```ts
export type WorkspaceSurface = 'editor' | 'library' | 'jobs' | 'settings'

interface WorkspaceShellProps {
  surface: WorkspaceSurface
  videoName: string | null
  videoMeta: string | null
  saved: boolean
  openingDisabled: boolean
  onSurfaceChange(surface: WorkspaceSurface): void
  onOpenUpload(file: File): Promise<void>
  topAction?: ReactNode
  canvas: ReactNode
  inspector: ReactNode
  timeline: ReactNode
  library: ReactNode
  jobs: ReactNode
  settings: ReactNode
}
```

Use a hidden file input in the top bar for Open Video. Drawers use
`role="dialog"`, `aria-modal="false"`, a visible close button, and Escape
handling. Restore focus to the activating rail button on close.

- [ ] **Step 4: Refactor Library and Settings content**

Add `query`, a search input, compact recent-video rows, source-kind labels,
track/export counts, and item disclosure. Keep the existing API mutations and
confirmations. Add `openingDisabled` and `onClose` props. Remove cache clearing
from Library.

`SettingsPanel` receives `cacheBytes`, `busy`, and `onClearFrameCaches`. It
renders the current cache size and requires the existing browser confirmation
before clearing.

Update `OpenVideoPanel` with `variant: 'empty' | 'drawer'`; both variants retain
file upload and server-path opening, but the drawer hides the path form under a
`<details>` labeled `More options`.

- [ ] **Step 5: Run the focused tests**

Run: `cd frontend && npm test -- src/components/WorkspaceShell.test.tsx src/components/LibraryPanel.test.ts src/components/OpenVideoPanel.test.tsx`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/WorkspaceShell.tsx frontend/src/components/WorkspaceShell.test.tsx frontend/src/components/SettingsPanel.tsx frontend/src/components/LibraryPanel.tsx frontend/src/components/LibraryPanel.test.ts frontend/src/components/OpenVideoPanel.tsx frontend/src/components/OpenVideoPanel.test.tsx
git commit -m "Build the editor shell and drawers"
```

---

### Task 5: Contextual Workflow Inspector and Compact Export

**Files:**

- Create: `frontend/src/components/WorkflowInspector.tsx`
- Create: `frontend/src/components/WorkflowInspector.test.tsx`
- Modify: `frontend/src/components/ExportPanel.tsx`
- Modify: `frontend/src/components/ExportPanel.test.ts`

**Interfaces:**

- Consumes: `WorkspaceStage`, selection/job/health state, feature flags, export
  identifiers, and existing callbacks.
- Produces: `WorkflowInspector` and `ExportPanelHandle`.

- [ ] **Step 1: Write failing inspector-state tests**

Render each stage and assert:

- Select has click instructions and shows Describe only when enabled.
- A confirmed selection has one `Track player` primary button.
- Track shows processed/total frames, percentage, progress, and Retry on failure.
- Review shows coverage/lost summaries and one button per lost range plus
  `Set framing`.
- Export renders `ExportPanel` and no earlier-step controls.

Update export tests to expect 720p selected, max acceleration/custom dimensions
inside `Advanced settings`, `Export MP4` copy, and no disabled locked panel.

- [ ] **Step 2: Run focused tests to verify red**

Run: `cd frontend && npm test -- src/components/WorkflowInspector.test.tsx src/components/ExportPanel.test.ts`

Expected: FAIL against the old export panel and missing inspector.

- [ ] **Step 3: Implement state-specific inspectors**

```ts
interface WorkflowInspectorProps {
  stage: WorkspaceStage
  video: VideoMetadata
  currentFrame: number
  selection: ClickSelection | null
  selectionKind: 'click' | 'text'
  selectionLoading: boolean
  selectionError: string | null
  candidates: readonly LocateCandidate[]
  textSelectionEnabled: boolean
  trackJob: TrackJobUpdate | null
  trackMessage: string | null
  trackError: string | null
  trackStartedAt: number | null
  health: TrackHealthSummary | null
  onTextSelect(prompt: string): void
  onTrack(): void
  onRetryTrack(): void
  onResetSelection(): void
  onBeginFraming(): void
  onSeek(frameIdx: number): void
  exportPanel: ReactNode
}
```

Render a shared inspector header and three-segment state marker. Keep candidate
confirmation instruction local to Select. Track processed frames are
`Math.min(video.nbFrames, Math.round(progress * video.nbFrames))`; do not show an
ETA. While a new job is active, update elapsed whole seconds from
`trackStartedAt` once per second with an interval that is cleared on terminal
state/unmount; omit elapsed time for restored jobs. Review lost-range buttons
seek to their start frame.

- [ ] **Step 4: Refactor `ExportPanel`**

```ts
export interface ExportPanelHandle { triggerExport(): void }

interface ExportPanelProps {
  videoId: string
  trackJobId: string
  onPlanChange(windows: CropWindow[]): void
  onJobChange(job: TrackJobUpdate | null): void
  onLibraryChange(): void
}
```

Convert to `forwardRef`. Remove the disabled/locked state because the inspector
mounts it only in Export. Use visible 1080p/720p preset buttons. Put Custom
dimensions and Max acceleration inside `<details>Advanced settings</details>`.
Debounce crop-preview requests by 150 ms and continue aborting stale requests.
On terminal export updates call `onJobChange`; on completion also call
`onLibraryChange`. Use `Export MP4`, `Download MP4`, and `Export another version`
copy.

- [ ] **Step 5: Run focused tests**

Run: `cd frontend && npm test -- src/components/WorkflowInspector.test.tsx src/components/ExportPanel.test.ts src/api.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/WorkflowInspector.tsx frontend/src/components/WorkflowInspector.test.tsx frontend/src/components/ExportPanel.tsx frontend/src/components/ExportPanel.test.ts
git commit -m "Add contextual workflow inspector"
```

---

### Task 6: Assemble the Editor, Add Shortcuts, and Apply the Visual System

**Files:**

- Create: `frontend/src/hooks/useWorkspaceShortcuts.ts`
- Create: `frontend/src/hooks/useWorkspaceShortcuts.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.test.ts`
- Modify: `frontend/src/styles.css`

**Interfaces:**

- Consumes: all components/controllers from Tasks 1–5.
- Produces: the complete approved workspace and keyboard routing.

- [ ] **Step 1: Write failing shortcut and app composition tests**

In jsdom, dispatch keyboard events and assert Space/Arrow/Enter/Cmd+K/Escape
callbacks. Repeat with focus in `<input>`, `<textarea>`, `<select>`, and
`contenteditable` and assert media/primary shortcuts are ignored. Render the
App shell with mocked API responses and assert that Library and future Export
controls are absent from the default editor surface.

- [ ] **Step 2: Run focused tests to verify red**

Run: `cd frontend && npm test -- src/hooks/useWorkspaceShortcuts.test.tsx src/App.test.ts`

Expected: FAIL because the hook and new composition are absent.

- [ ] **Step 3: Implement guarded shortcuts**

```ts
interface WorkspaceShortcutActions {
  togglePlayback(): void
  stepFrames(delta: number): void
  primaryAction(): void
  openLibrary(): void
  closeSurface(): void
}

export function useWorkspaceShortcuts(actions: WorkspaceShortcutActions): void
```

Ignore events whose target is `input`, `textarea`, `select`, `button`, `a`, or
contenteditable. Ignore modified Space/Arrow/Enter. Cmd/Ctrl+K always prevents
the browser default outside editable targets. Escape closes only when a
secondary surface is active.

- [ ] **Step 4: Compose `App`**

Use `useWorkspace`, a `VideoStageHandle` ref, an `ExportPanelHandle` ref,
`summarizeTrack`, `WorkspaceShell`, `WorkflowInspector`, `TrackTimeline`,
`LibraryPanel`, and `SettingsPanel`. Maintain `surface` locally. The primary
shortcut dispatches by stage: Track, Set Framing, or Export. Timeline/range
seeks call `videoRef.current?.seekToFrame`.

Jobs drawer renders the current track/export job with message, progress,
processed frames, and terminal state. Opening/re-export is disabled when
`videoSwitchLocked`. The empty canvas contains `OpenVideoPanel variant="empty"`
and local open errors.

- [ ] **Step 5: Replace the stylesheet with the approved tokens/layout**

Define CSS custom properties for graphite surfaces, amber, mint, orange, red,
text, muted text, borders, radii, and 120–180 ms motion. Implement:

- full-viewport three-column/two-row editor shell;
- 52–58 px activity rail;
- flexible center canvas with 320 px inspector;
- 104–116 px timeline;
- on-demand 340 px drawers;
- compact rectangular controls and status-only pills;
- visible `:focus-visible` outlines;
- `prefers-reduced-motion` overrides;
- at `max-width: 1100px`, a 290 px inspector and condensed labels;
- at `max-width: 860px`, single-column content, fixed bottom activity nav,
  bottom-sheet inspector, and condensed timeline.

Do not alter canvas sizing contracts: `.video-stage video` and overlay layers
remain absolute, full-size, and `object-fit: contain`.

- [ ] **Step 6: Run all frontend tests and typecheck**

Run: `cd frontend && npm test && npm run typecheck`

Expected: all tests PASS and TypeScript exits 0.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.ts frontend/src/hooks/useWorkspaceShortcuts.ts frontend/src/hooks/useWorkspaceShortcuts.test.tsx frontend/src/styles.css
git commit -m "Redesign the FindMe editor workspace"
```

---

### Task 7: Full Verification and Real-Flow Check

**Files:**

- Modify only files required by failures found during verification.

**Interfaces:**

- Consumes: the completed frontend redesign.
- Produces: evidence that existing backend behavior and the production bundle
  remain intact.

- [ ] **Step 1: Run the complete weight-free backend suite**

Run: `cd backend && uv run --extra dev pytest -m "not integration"`

Expected: all collected non-integration tests PASS.

- [ ] **Step 2: Run the complete frontend suite and build**

Run: `cd frontend && npm test && npm run build`

Expected: all Vitest tests PASS; TypeScript and Vite production build exit 0.

- [ ] **Step 3: Check repository hygiene**

Run: `git diff --check && git status --short`

Expected: no whitespace errors; only intended implementation/plan changes are
present. `.superpowers/` does not appear because `.gitignore` excludes it.

- [ ] **Step 4: Exercise the real flow when local prerequisites exist**

Run these prerequisite checks first:

```bash
test -f examples/example.mp4
test -f checkpoints/sam2.1_hiera_base_plus.pt
```

If both pass, start the existing backend/frontend dev flow without killing any
already-running project process, then exercise register → click select → track
→ review lost ranges → crop preview → export. Verify the newest MP4 with:

```bash
find exports -type f -name '*.mp4' -print0 | xargs -0 ls -t | head -1 | xargs ffprobe -v error -show_entries stream=codec_name,width,height -of json
```

Visually inspect the selection label, live track box, lost-range navigation,
crop overlay, drawer behavior, and representative exported frames. If either
prerequisite is absent, record that the real-flow check was not run and why.

If verification reveals a defect, return to the owning task, add a failing
regression test there, apply the minimal fix, rerun that task's focused command,
and commit the exact test and implementation files with subject
`Fix UI redesign verification issue` before repeating Steps 1–4.
