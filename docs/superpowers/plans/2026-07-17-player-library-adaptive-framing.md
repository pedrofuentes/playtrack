# Player Library and Adaptive Framing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make saved tracks named, clearly browsable players and guarantee visibility-safe smooth framing with reliable saved-player overlays.

**Architecture:** Extend the existing JSON track record compatibly, keep the nested Library API, and derive three frontend views. Extend the pure crop planner with track boxes and asymmetric adaptive zoom. Make saved-player restoration atomic and draw playback-dependent overlays from one shared clock.

**Tech Stack:** Python 3.12, FastAPI, NumPy, pytest, React 19, TypeScript, Vitest.

## Global Constraints

- Preserve legacy smoothing request keys and existing Library deletion cascades.
- Never delete registered-by-path source files.
- Player names are trimmed to 1-80 characters; initial blank names auto-allocate `Player N`.
- Preview and export must consume the identical crop plan.
- Every behavior change follows red-green-refactor.

---

### Task 1: Named-player persistence and API

**Files:** `backend/app/library.py`, `backend/app/main.py`, tracking/API tests.

**Interfaces:** `SavedTrack.name: str`; `resolve_player_name(video_id, requested) -> str`; `rename_track(job_id, name) -> SavedTrack`; track start returns `{jobId, playerName}`.

- [ ] Add failing persistence tests for explicit names, automatic `Player N`, legacy backfill ordering, and rename.
- [ ] Run focused tests and confirm missing-field/API failures.
- [ ] Add crash-safe name persistence/backfill/allocation and the PATCH endpoint.
- [ ] Add failing track-start tests for blank, trimmed, duplicate explicit, and overlong names.
- [ ] Pass the resolved name through tracking completion and expose it in Library.
- [ ] Run backend Library and track API tests, then commit.

### Task 2: Adaptive crop containment

**Files:** `backend/app/crop_planner.py`, `backend/app/main.py`, crop/export tests.

**Interfaces:** `plan_crop_windows(..., boxes: Sequence[Box | None] | None = None)`; boxes align one-to-one with centers.

- [ ] Add failing tests proving full-box containment, inner-80% padding, immediate widening, slow 0.75s return, held lost-frame scale, and even source-clamped windows.
- [ ] Confirm the existing step/sprint fixture violates containment before implementation.
- [ ] Implement required crop scale, asymmetric easing, and final minimal containment projection.
- [ ] Pass completed-track boxes from `build_export_plan`; retain old behavior only for direct callers omitting boxes.
- [ ] Run crop and export tests, then commit.

### Task 3: Frontend player contracts and Library tabs

**Files:** `frontend/src/api.ts`, Library panel/component tests, workspace inspector tests.

**Interfaces:** `LibraryTrack.name`; `startTracking(..., playerName?) -> {jobId, playerName}`; `renameLibraryPlayer(jobId, name)`.

- [ ] Add failing API serialization tests for starting/renaming players.
- [ ] Add failing Library interaction tests for Sources/Players/Exports separation, active-tab search, exact actions, inline rename, and missing-source behavior.
- [ ] Implement API types/client functions and the three-tab Library UI.
- [ ] Add the optional name field to selection state and pass it into tracking.
- [ ] Run focused frontend tests, then commit.

### Task 4: Atomic restore and shared playback overlay

**Files:** workspace controller, video-stage overlay components, related interaction tests.

**Interfaces:** `openLibraryPlayer(video, player): Promise<boolean>` restores video, player identity, completed track, anchor frame, and Review state atomically.

- [ ] Add a failing controller test that a successful restore commits all state at once and a failed restore preserves the prior editor.
- [ ] Add failing playback tests proving restored player/crop geometry advances on play and seek from one frame clock.
- [ ] Implement `openLibraryPlayer`, close Library only after `true`, and seek to the anchor once video metadata is ready.
- [ ] Replace independent track/crop animation loops with one playback overlay while retaining pure frame lookup helpers.
- [ ] Verify Review shows player only and Framing shows player plus crop; run focused tests and commit.

### Task 5: Full verification and live regression check

- [ ] Run `uv run --extra dev pytest -m "not integration"`.
- [ ] Run `npm test` and `npm run build`.
- [ ] Run `git diff --check` and review schema migration/deletion safety.
- [ ] Against the local saved 930-frame track, request the 3.4x/1.2s plan and assert zero full-box containment violations.
- [ ] Exercise Library Sources/Players/Exports and saved-player restore in the running app; visually confirm playback overlays.
- [ ] Commit any test-first review corrections and proceed through branch completion.
