# Selection Frame Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep every selection overlay tied to its exact source frame, show inclusive Out labels, and accurately model Library metadata.

**Architecture:** `VideoStage` owns the exact media-time freeze and rejects every frame mutation while playback is selection-locked. `App` passes the exact paused frame to `useWorkspace`, which validates range and candidate-frame identity. Half-open range math remains unchanged; only display formatting uses the final included frame. Library payload types separate technical nested metadata from the top-level display name and reconstruct active `VideoMetadata` at the workspace boundary.

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
- Produces: `VideoStageHandle.pause(): number | null` returning the displayed frame and reporting it through `onFrameChange`.
- Produces: `WorkspaceController.selectByDescription(prompt: string, frameIdx?: number): void`.

- [ ] **Step 1: Write failing VideoStage tests**

Add tests that set media time to frame 37, call `pause()`, and assert the return value and `onFrameChange(37)`. After rerendering with `playbackLocked`, call `seekToFrame`, `stepFrames`, and dispatch native `seeking`/`seeked` events after changing `currentTime`; assert media time and frame reporting remain at frame 37.

- [ ] **Step 2: Write failing App tests**

Make the mocked handle expose `pause`, `seekToFrame`, and `stepFrames` spies. Return frame 37 from `pause()` while workspace `currentFrame` is 10, submit text selection, and expect `selectByDescription('white jersey', 37)`. Dispatch ArrowRight while selection is loading/candidates/confirmed and expect `stepFrames` not to run.

- [ ] **Step 3: Write failing workspace test**

Call `selectByDescription('white jersey', 37)` while `currentFrame` is 10 and assert `/api/select/text` receives frame 37 and candidate confirmation state remains anchored to 37.

- [ ] **Step 4: Run the focused RED tests**

Run:

```bash
cd frontend && npm test -- --run src/components/VideoStage.interaction.test.tsx src/App.test.ts src/hooks/useWorkspace.test.tsx
```

Expected: failures showing `pause()` returns no frame, navigation mutates media time, App passes only the prompt, and workspace submits the lagging current frame.

- [ ] **Step 5: Implement the media freeze**

In `VideoStage`, store `frozenFrameRef`. Implement `pauseAtDisplayedFrame()` to pause, calculate with `displayedFrameIndex`, store/report/return the frame, and use it for both imperative `pause()` and clicks. Reject `seekToFrame` and `stepFrames` while locked. On native frame-reporting events, restore `frozenFrame / fps` and report the frozen frame when locked; clear the ref only when the lock is released or `src` changes.

- [ ] **Step 6: Pass exact frame through App and workspace**

In App text selection:

```ts
const frameIdx = videoStageRef.current?.pause()
workspace.selectByDescription(prompt, frameIdx ?? workspace.currentFrame)
```

Guard shortcut stepping with `!playbackLocked`. In `useWorkspace`, resolve `selectionFrame = frameIdx ?? currentFrame` once and use it for range validation, `prepareSelection`, the request, and `candidateFrame`.

- [ ] **Step 7: Run focused GREEN tests**

Run the Step 4 command and expect all tests to pass without React act warnings.

### Task 2: Candidate identity and outside-range validation

**Files:**
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/App.test.ts`
- Modify: `frontend/src/hooks/useWorkspace.ts`
- Test: `frontend/src/hooks/useWorkspace.test.tsx`

**Interfaces:**
- Consumes: exact selection frame from Task 1.
- Preserves: `confirmCandidate(candidate, frameIdx)` but validates `frameIdx === candidateFrame`.

- [ ] **Step 1: Write failing regressions**

Add an App interaction assertion that an outside-range Select frame is not VideoStage-locked and its source click reaches `workspace.selectAt`. Extend the workspace outside-range test to assert the inline range error and zero request. Add a candidate test that receives candidates at frame 37, rejects confirmation at frame 38, and accepts confirmation at frame 37.

- [ ] **Step 2: Run RED tests**

Run:

```bash
cd frontend && npm test -- --run src/App.test.ts src/hooks/useWorkspace.test.tsx
```

Expected: App still locks the outside-range click and workspace accepts an arbitrary in-range candidate frame.

- [ ] **Step 3: Implement validation**

Remove current-range containment from App's `selectionLocked`; keep loading, tracking-start, and non-Select locks. In `confirmCandidate`, reject unless `candidateFrame !== null && frameIdx === candidateFrame`, then retain the existing selected-range validation and install the candidate.

- [ ] **Step 4: Run GREEN tests**

Run the Step 2 command and expect both files to pass.

### Task 3: Inclusive Out timestamp display

**Files:**
- Modify: `frontend/src/components/TrackTimeline.tsx`
- Test: `frontend/src/components/TrackTimeline.test.tsx`
- Modify: `frontend/src/components/LibraryPanel.tsx`
- Test: `frontend/src/components/LibraryPanel.test.tsx`

**Interfaces:**
- Consumes: half-open `FrameRange`.
- Displays: Out timestamp at `endFrameExclusive - 1`; duration remains `frameRangeCount(range) / fps`.

- [ ] **Step 1: Write low-fps RED tests**

For fps 2 and range `[2, 4)`, assert TrackTimeline shows `00:01.0–00:01.5 · 1.0 sec · 2 frames`, and Library shows `00:01–00:01 · 1.0 sec · 2 frames`. Update the legacy full-range expectation from final boundary time to final included frame time.

- [ ] **Step 2: Run RED tests**

Run:

```bash
cd frontend && npm test -- --run src/components/TrackTimeline.test.tsx src/components/LibraryPanel.test.tsx
```

Expected: old boundary displays `00:02.0` / `00:02`.

- [ ] **Step 3: Implement inclusive display**

Use the existing `outFrameIdx = safeRange.endFrameExclusive - 1` in the timeline summary. In `formatPlayerRange`, pass `range.endFrameExclusive - 1` to the Out formatter. Leave count and duration unchanged.

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

Type the `/api/library` result fixture with `satisfies LibraryResponse` while nested metadata contains `videoId`, dimensions, fps, frame count, and duration but no `name`. Assert `getLibrary()` returns it unchanged.

- [ ] **Step 2: Run build RED**

Run:

```bash
cd frontend && npm run build
```

Expected before the type split: TypeScript reports missing `name` on nested metadata.

- [ ] **Step 3: Split and adapt types**

Add the name-less metadata type and assign it to `LibraryVideo.metadata`. Convert saved metadata back to `VideoMetadata` only in `openLibraryVideo` and the successful `openLibraryPlayer` commit by spreading nested metadata and top-level `saved.name`. Remove nested names from test fixtures.

- [ ] **Step 4: Run contract and workspace tests**

Run:

```bash
cd frontend && npm test -- --run src/api.test.ts src/hooks/useWorkspace.test.tsx src/components/LibraryPanel.test.tsx src/App.test.ts
```

Expected: all pass.

### Task 5: Verification and handoff

**Files:**
- Modify: `.superpowers/sdd/task-7-report.md`

- [ ] **Step 1: Run focused Task 7 tests**

Run the nine-file focused Task 7 command and record exact counts.

- [ ] **Step 2: Run full frontend and build**

Run `npm test` and `npm run build` from `frontend`; require zero failures/errors.

- [ ] **Step 3: Check scope and preserved invariants**

Run `git diff --check`, inspect `git status --short`, confirm `sourceStartFrame` remains in API/backend/export wiring, and confirm the `loadingRef`/`trackStartingRef` guards remain in `useWorkspace`.

- [ ] **Step 4: Update report and commit**

Record RED/GREEN and verification evidence in the ignored Task 7 report. Stage only Task 7 frontend/doc files and commit with an imperative subject.
