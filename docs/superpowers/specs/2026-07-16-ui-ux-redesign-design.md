# FindMe UI/UX Redesign

## Status

Approved design. This document defines a frontend-led redesign of the existing
single-video FindMe workflow. It preserves the working backend, API contracts,
video geometry, model behavior, and export pipeline.

## Objective

Optimize FindMe for fast repeat use on desktop. A returning user should be able
to open footage, choose a player, start tracking, review track health, set the
crop, and export without navigating through wizard pages or searching a dense
sidebar for the next action.

One active video at a time remains an accepted product constraint. Opening a
different video is unavailable while tracking or export is running.

## Current UX diagnosis

The current two-column screen puts every concern in one 18-rem details rail:
opening videos, the saved library, workflow steps, video metadata, click
coordinates, selection, tracking progress, and export settings. This creates
four related problems:

- The video competes with controls and bookkeeping instead of remaining the
  stable focus of the product.
- The current action is not visually dominant because future, disabled, and
  secondary controls remain visible beside it.
- Tracking and export can take minutes, but their progress is embedded among
  unrelated controls.
- The library and storage-management UI permanently occupy the editing
  workspace even though they are used only occasionally.

The app state and backend flow are sound. The redesign therefore changes the
information architecture and presentation rather than the processing model.

## Chosen direction: pro editor

FindMe uses a desktop editor layout with five stable regions:

1. A compact top bar identifies the active video and exposes global actions.
2. A narrow activity rail opens Editor, Library, Jobs, and Settings surfaces.
3. The video canvas occupies the center and does not move between workflow
   states.
4. A contextual inspector on the right shows only the current task and its
   relevant settings.
5. A bottom timeline shows playhead position, tracking coverage, and track
   health.

This structure favors spatial memory: playback stays in one place, the primary
action is always in the inspector, and progress remains visible without
covering the footage.

The rejected alternatives were a shortcut-heavy command workspace and a
phase-by-phase wizard. The command workspace would require too much learned
behavior, while the wizard would slow repeat use and hide cross-step context.

## Workspace architecture

### Top bar

The top bar contains:

- the current filename;
- concise source metadata (`4096 × 1024`, duration) behind or beside the name;
- saved/working state when useful;
- Open Video;
- the current global export/download action when available; and
- a Cmd/Ctrl+K command trigger for opening recent videos.

Large marketing copy, the current oversized title, and persistent instructions
do not appear once the editor is open.

### Activity rail

The rail uses labeled icons with tooltips for:

- Editor: return to the active workflow;
- Library: open the video/history drawer;
- Jobs: show the current tracking or export job and recent completed output;
- Settings: storage maintenance and advanced application settings.

The rail is navigation, not a second toolbar. It remains narrow and never holds
forms or destructive actions.

### Video canvas

`VideoStage` remains the product's visual center. Existing video playback,
letterbox-aware coordinates, click selection, zoom/pan, masks, tracking boxes,
and crop overlays keep their current geometry and API behavior.

Canvas instructions are short overlays that disappear when no longer useful.
Zoom controls use compact rectangular buttons and a Fit action. The selected
player has both a colored outline and a text label, so selection is not conveyed
by color alone.

### Contextual inspector

The inspector renders exactly one workflow state at a time. It never shows a
fully disabled future panel. A three-segment progress marker communicates the
broad Select, Track/Review, and Export stages without behaving like mandatory
wizard navigation.

The inspector maintains one obvious primary action. Secondary and advanced
actions use lower visual emphasis.

### Timeline

The timeline appears below the canvas after a video opens. Before tracking it
acts as a playhead and frame ruler. While tracking, partial coverage fills in as
WebSocket updates arrive. After tracking, it shows healthy, lost, and
needs-review ranges. A needs-review range is a contiguous run of frames marked
`lost`; the UI does not infer identity switches from otherwise valid boxes.

Clicking a range seeks the video to its first frame. The timeline always pairs
color with a label, icon, pattern, or tooltip.

## Fast workflow

### 1. Open

Open Video in the top bar launches the native file picker. The Library drawer
provides recent videos, upload/drop, search, and a less-prominent server-path
option. The empty editor uses a central drop target instead of a permanent open
form in the inspector.

Opening a recent video takes at most two interactions. Opening another video is
disabled while a track or export job is queued or running.

### 2. Select

The Select inspector tells the user to scrub to a clear frame and click a
player. On CUDA, a Click/Describe segmented control exposes text selection. On
non-CUDA devices the Describe method is absent rather than disabled.

After selection, the inspector shows a small player thumbnail, anchor time, and
confidence as secondary detail. The primary action becomes Track Player.
Choosing another player is always available and clears downstream track/crop
state using the existing behavior.

### 3. Track

Tracking progress shows processed frames, total frames, percentage, elapsed
time, and the backend's current status message. It does not claim an ETA because
the current API does not provide a reliable estimate.

Partial boxes and timeline coverage appear during propagation. Playback,
scrubbing, zoom, and pan remain usable. Video switching and export are
unavailable until tracking reaches a terminal state.

### 4. Review

When tracking completes, the inspector summarizes:

- coverage percentage;
- lost-frame count;
- contiguous lost ranges; and
- a jump action for each range.

Track-health ranges are derived from the existing `TrackFrame` list. This phase
does not attempt automatic identity-switch detection, which the current data
cannot reliably provide. Multi-anchor correction and splicing remain separate
future work.

The user may scrub the overlay before choosing Set Framing.

### 5. Frame and export

Common output presets appear first. The default is 1280 × 720. The crop overlay
updates as resolution, zoom, and smoothing change.

Zoom and camera smoothness remain first-class controls. Max acceleration and
custom even dimensions move under Advanced Settings. Validation stays beside
the affected setting.

Export MP4 is the sole primary action. During export, the inspector becomes a
job view with progress. On completion it exposes Download MP4 and a secondary
Export Another Version action. Completed outputs remain available from the
Library.

## Library, jobs, and storage

The Library is an on-demand drawer rather than permanent editor content. Each
video row shows filename, last-opened date, track count, export count, and
source availability. Expanding or opening an item reveals its tracks and
exports without placing every nested record in the initial list.

Per-item overflow menus hold Re-export, Download, and Delete. Delete uses an
explicit confirmation that names the affected item. Registered files are never
presented as deletable source media. Uploaded copies are labeled so deletion
semantics are clear and continue to follow backend safeguards.

Jobs shows the one active tracking or export job and its most recent terminal
result. It is not a multi-video queue manager. Cache size and Clear Frame Cache
move to Settings.

## Visual language

The visual direction is a "broadcast analysis desk": technical and focused,
with enough warmth to feel like a finished product rather than a model demo.

### Color roles

- Near-black graphite is the page and canvas surround.
- Slightly lighter graphite separates rails, inspectors, drawers, and controls.
- Warm amber is reserved for the current primary action and crop framing.
- Mint indicates a confirmed selection, completed work, or healthy coverage.
- Orange marks ranges that need review.
- Soft red is reserved for failures and destructive confirmations.

Every state also includes text, iconography, or pattern. Color is never the
only signal.

### Type and geometry

Use the existing system sans-serif stack, with tabular numerals for frames,
time, percentages, and dimensions. Hierarchy comes from weight, size, and
spacing rather than a decorative display face.

Controls use 6–10 px radii. Pills are reserved for compact status labels. Rail
and inspector borders are quiet, and shadows are limited to drawers, menus, and
canvas elevation.

### Motion

Use 120–180 ms transitions for drawers, popovers, hover states, and inspector
state changes. Respect `prefers-reduced-motion`. Model jobs do not use looping
ornamental animation; determinate progress and plain status text communicate
activity.

## Keyboard and accessibility

Desktop accelerators are:

- Space: play or pause when focus is not inside a text or form control;
- Left/Right: seek by one frame;
- Enter: invoke the current inspector's primary action when focus is not in a
  multiline or conflicting form control;
- Cmd/Ctrl+K: open the recent-video command surface;
- Escape: close the current drawer, popover, or menu.

All shortcuts have clickable equivalents and must not override native editing
keys in inputs. Focus returns to the trigger when a drawer closes. Drawers and
dialogs trap focus where appropriate. All controls retain visible focus styles,
semantic labels, and keyboard operation.

## Responsive behavior

The redesign is desktop-first. At narrower desktop widths, the activity rail
and a roughly 300 px inspector remain visible while secondary labels condense.

Below the editor breakpoint, the inspector becomes a bottom sheet and the
timeline collapses to a compact health strip. The activity rail becomes a
bottom navigation bar. Mobile remains usable for inspection and simple actions,
but pixel-dense player selection is not treated as a primary phone workflow.

## Frontend component boundaries

`App.tsx` becomes a thin composition root. Its current workflow state moves to
a dedicated controller hook or reducer with explicit actions for open, select,
track update, track completion/failure, crop-plan update, export update, and
reset. The state model remains compatible with the current typed API client.

Proposed components and modules:

- `WorkspaceShell`: top bar, activity rail, responsive regions, and surface
  focus management;
- `TopBar`: active file identity and global actions;
- `ActivityRail`: Editor/Library/Jobs/Settings navigation;
- `WorkflowInspector`: chooses one inspector state;
- `SelectionInspector`, `TrackingInspector`, `ReviewInspector`, and
  `ExportInspector`: state-specific controls;
- `TrackTimeline`: playhead, partial coverage, lost ranges, and seeking;
- `LibraryDrawer`: open/upload/search and saved item actions;
- `JobStatus`: the current long-running operation;
- `trackHealth.ts`: pure track-summary and contiguous-range derivation;
- `shortcuts.ts` or `useWorkspaceShortcuts`: guarded keyboard behavior.

`VideoStage`, `TrackOverlay`, `CropOverlay`, `geometry.ts`, and the typed API
client retain their existing responsibilities. Export settings may be split
from `ExportPanel`, but the existing API calls and preview cancellation behavior
remain intact.

## Data flow

1. Opening a video resets selection, track, crop, and export state while keeping
   global library data.
2. A click or text candidate creates the current selection and anchor frame.
3. Track Player starts the existing tracking job. WebSocket updates populate
   job status, partial track frames, overlays, and timeline coverage from a
   single state source.
4. Completion derives a memoized track-health summary from the final frames.
5. Export control changes request the existing crop preview with stale requests
   aborted. Slider-driven preview requests use a 150 ms debounce to avoid
   redundant calls while dragging.
6. Export starts the existing job and reuses the same job-status presentation.
7. Terminal track/export updates refresh the persisted library.

No backend route, persisted schema, or model pipeline change is required.

## Error handling

Errors render beside the operation that failed:

- open failures remain in the empty canvas or Library drawer;
- selection failures preserve the current frame and allow another click/prompt;
- tracking failures preserve the selection and any received partial frames,
  offer Retry, and expose technical details on demand;
- crop-preview failures preserve settings and offer Retry;
- export failures preserve settings and the completed track;
- missing saved sources are labeled in Library and disable only impossible
  actions.

Stale selection and crop-preview requests continue to be aborted. Error copy
must state what was preserved and the next available recovery action.

## Testing and verification

Weight-free frontend tests cover:

- the workflow reducer/controller transitions and reset rules;
- one inspector state and primary action at a time;
- CUDA and non-CUDA selection-method presentation;
- keyboard shortcuts and input-focus guards;
- track coverage, lost count, contiguous range derivation, and range seeking;
- drawer focus/escape behavior and video-switch locking during active jobs;
- local recovery states and preserved valid data;
- export defaults, advanced-setting validation, and preview cancellation; and
- responsive region behavior at representative breakpoints.

Existing `geometry.ts`, overlay, API, and export tests remain unchanged unless
their markup-facing assertions require an intentional update.

Before completion, run:

```bash
cd backend && uv run --extra dev pytest -m "not integration"
cd frontend && npm test && npm run build
```

Exercise the real `examples/example.mp4` flow when the local asset is present:
register or upload, select, track, review health, preview crop, export, inspect
the output with `ffprobe`, and visually inspect overlays and representative
frames. Report when the local test asset or model checkpoint makes that flow
unavailable rather than implying it ran.

## Acceptance criteria

- The default editing workspace contains no permanently expanded library,
  storage, source-coordinate, or future-step panels.
- A recent video opens in two interactions or fewer.
- After clicking a player, one visible primary action starts tracking.
- Tracking/export progress stays visible without blocking video playback.
- A completed track reports coverage and lost segments, and each segment can
  seek the video to its first frame.
- Export controls preview the crop and keep advanced settings out of the common
  path.
- Errors preserve valid work and present a local, actionable recovery.
- Existing backend contracts and video geometry remain unchanged.
- The weight-free backend suite, frontend suite, and production build pass.

## Out of scope

- Multi-video background processing or a job queue;
- multi-anchor track splicing or identity-switch detection;
- backend API or persistence changes;
- authentication and LAN hardening;
- model behavior, tracking speed, or export codec changes; and
- packaging or installer work.
