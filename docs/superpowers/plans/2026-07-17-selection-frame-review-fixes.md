# Selection Frame Review Fixes Implementation Plan

**Date:** 2026-07-17

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep every click-selection overlay tied to its exact source frame,
show inclusive Out labels, and accurately model Library metadata.

**Architecture:** `VideoStage` owns the exact media-time freeze, includes the
displayed frame in its click callback, and rejects frame mutation while
playback is selection-locked. `useWorkspace` validates the supplied click frame
against the active range. Half-open range math remains unchanged; only display
formatting uses the final included frame. Library payload types separate
technical nested metadata from the top-level display name and reconstruct
active `VideoMetadata` at the workspace boundary.

**Tech Stack:** React 19, TypeScript, Vitest/jsdom, Vite.

## Global Constraints

- Preserve `[startFrameIdx, endFrameExclusive)` computation and API payloads.
- Preserve the synchronous open/tracking mutual exclusion introduced in `3c677ec`.
- Do not modify backend code for the Library metadata type split.
- Do not stage concurrent backend edits, `backend/.venv`, or `frontend/node_modules`.

---

### Task 1: Exact media-frame freeze

**Files:**
- Modify: `frontend/src/components/VideoStage.tsx`
- Test: `frontend/src/components/VideoStage.interaction.test.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/App.test.ts`
- Modify: `frontend/src/hooks/useWorkspace.ts`
- Test: `frontend/src/hooks/useWorkspace.test.tsx`

**Interfaces:**
- Produces: `VideoStageHandle.pause(): number | null` returning and reporting the displayed frame.
- Produces: `VideoStageProps.onSourceClick(point: Point, frameIdx: number): void`.

- [ ] **Step 1: Write failing VideoStage tests**

Set media time to frame 37, call `pause()`, and assert the return value and
`onFrameChange(37)`. Trigger a source click and assert the callback receives
frame 37 after `pause()` runs. After rerendering with `playbackLocked`, call
`seekToFrame`, `stepFrames`, and dispatch native `seeking`/`seeked` events after
changing `currentTime`; assert media time and frame reporting remain at frame 37.

- [ ] **Step 2: Write failing App/workspace tests**

Assert App passes `workspace.selectAt` as the two-argument source-click handler.
Call `selectAt(point, 37)` while `currentFrame` is 10 and assert the click API
receives frame 37. Dispatch ArrowRight while selection is loading or confirmed
and expect `stepFrames` not to run.

- [ ] **Step 3: Run the focused RED tests**

```bash
cd frontend && npm test -- --run src/components/VideoStage.interaction.test.tsx src/App.test.ts src/hooks/useWorkspace.test.tsx
```

Expected: failures show that the click callback lacks an exact frame and locked
navigation still mutates media time.

- [ ] **Step 4: Implement the media freeze and exact callback**

In `VideoStage`, store `frozenFrameRef`. Implement `pauseAtDisplayedFrame()` to
pause, calculate with `displayedFrameIndex`, store/report/return the frame, and
use it for both imperative `pause()` and clicks. Pass that frame with the mapped
source point. Reject `seekToFrame` and `stepFrames` while locked. On native
frame-reporting events, restore `frozenFrame / fps` and report the frozen frame
when locked; clear the ref only when the lock is released or `src` changes.

In App, wire `onSourceClick={workspace.selectAt}` and guard shortcut stepping
with `!playbackLocked`. In `useWorkspace`, use the callback's frame once for
range validation, request preparation, and the click request.

- [ ] **Step 5: Run focused GREEN tests**

Run the Step 3 command and expect all tests to pass without React act warnings.

### Task 2: Outside-range validation

**Files:**
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/App.test.ts`
- Modify: `frontend/src/hooks/useWorkspace.ts`
- Test: `frontend/src/hooks/useWorkspace.test.tsx`

- [ ] **Step 1: Write failing regressions**

Add an App assertion that an outside-range frame in Select is not locked before
the click reaches workspace validation. Extend the workspace test to assert the
inline range error and zero click-selection requests.

- [ ] **Step 2: Run RED tests**

```bash
cd frontend && npm test -- --run src/App.test.ts src/hooks/useWorkspace.test.tsx
```

Expected: App still blocks the outside-range click.

- [ ] **Step 3: Implement validation**

Remove current-range containment from App's `selectionLocked`; keep loading,
tracking-start, confirmed-selection, and non-Select locks. Let `selectAt`
perform the authoritative range check before issuing the request.

- [ ] **Step 4: Run GREEN tests**

Run the Step 2 command and expect both files to pass.

### Task 3: Inclusive Out timestamp display

**Files:**
- Modify: `frontend/src/components/TrackTimeline.tsx`
- Test: `frontend/src/components/TrackTimeline.test.tsx`
- Modify: `frontend/src/components/LibraryPanel.tsx`
- Test: `frontend/src/components/LibraryPanel.test.tsx`

- [ ] **Step 1: Write low-fps RED tests**

For fps 2 and range `[2, 4)`, assert TrackTimeline shows
`00:01.0–00:01.5 · 1.0 sec · 2 frames`, and Library shows
`00:01–00:01 · 1.0 sec · 2 frames`. Update the legacy full-range expectation
from final boundary time to final included frame time.

- [ ] **Step 2: Run RED tests**

```bash
cd frontend && npm test -- --run src/components/TrackTimeline.test.tsx src/components/LibraryPanel.test.tsx
```

Expected: old boundary displays `00:02.0` / `00:02`.

- [ ] **Step 3: Implement inclusive display**

Use the existing `outFrameIdx = safeRange.endFrameExclusive - 1` in the timeline
summary. In `formatPlayerRange`, pass `range.endFrameExclusive - 1` to the Out
formatter. Leave count and duration unchanged.

- [ ] **Step 4: Run GREEN tests**

Run the Step 2 command and expect both files to pass.

### Task 4: Library metadata contract

**Files:**
- Modify: `frontend/src/api.ts`
- Test: `frontend/src/api.test.ts`
- Modify: `frontend/src/hooks/useWorkspace.ts`
- Test: `frontend/src/hooks/useWorkspace.test.tsx`
- Update fixtures: `frontend/src/components/LibraryPanel.test.tsx`, `frontend/src/App.test.ts`

**Interfaces:**
- Produces: `LibraryVideoMetadata = Omit<VideoMetadata, 'name'>`.
- Produces: active video conversion `{ ...saved.metadata, name: saved.name }`.

- [ ] **Step 1: Write the contract test**

Type the `/api/library` result fixture with `satisfies LibraryResponse` while
nested metadata contains `videoId`, dimensions, fps, frame count, and duration
but no `name`. Assert `getLibrary()` returns it unchanged.

- [ ] **Step 2: Run build RED**

```bash
cd frontend && npm run build
```

Expected before the type split: TypeScript reports missing `name` on nested metadata.

- [ ] **Step 3: Split and adapt types**

Add the name-less metadata type and assign it to `LibraryVideo.metadata`.
Convert saved metadata back to `VideoMetadata` only in `openLibraryVideo` and
the successful `openLibraryPlayer` commit by spreading nested metadata and
top-level `saved.name`. Remove nested names from test fixtures.

- [ ] **Step 4: Run contract and workspace tests**

```bash
cd frontend && npm test -- --run src/api.test.ts src/hooks/useWorkspace.test.tsx src/components/LibraryPanel.test.tsx src/App.test.ts
```

Expected: all pass.

### Task 5: Verification and handoff

- [ ] Run the focused Task 7 tests and record exact counts.
- [ ] Run `npm test` and `npm run build` from `frontend`; require zero failures/errors.
- [ ] Run `git diff --check`, inspect `git status --short`, confirm `sourceStartFrame`
  remains in API/backend/export wiring, and confirm the `loadingRef` and
  `trackStartingRef` guards remain in `useWorkspace`.
- [ ] Record RED/GREEN and verification evidence in the ignored Task 7 report,
  stage only Task 7 frontend/doc files, and commit with an imperative subject.
