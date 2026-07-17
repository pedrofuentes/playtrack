# Source Identity, Naming, Selection Lock, and Tracking Ranges Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deduplicate source videos, add source naming and readable export filenames, freeze playback during player selection, and track/export only a user-selected contiguous frame range.

**Architecture:** The backend owns durable source identity, names, track ranges, migration, and attachment naming. Tracking-frame caches remain zero-based for SAM 2 but carry an absolute source-frame offset; saved tracks retain absolute indexes. The React workspace owns the selected range, while `VideoStage` owns synchronous playback pausing and `TrackTimeline` owns accessible range controls.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, PyAV, OpenCV, NumPy, React, TypeScript, Vitest, pytest, Vite

## Global Constraints

- Registered paths deduplicate by canonical resolved path; uploads deduplicate by SHA-256 only within uploaded sources.
- Existing duplicates must merge without losing tracks or exports; registered media must never be deleted.
- Uploaded media may be deleted only under `data/uploads/`, and only after successful reference/catalog rewrites.
- Source and player names are trimmed and limited to 80 characters.
- Tracking ranges use `[startFrameIdx, endFrameExclusive)` internally and contain at least one frame.
- Saved `TrackFrame.frameIdx` values remain absolute source indexes.
- Smoothing legacy keys remain accepted.
- Unmarked backend tests must not require model weights, a network, or a GPU.
- The frontend production bundle must be rebuilt before deployment.

---

## File Structure

- `backend/app/library.py`: persisted source keys/names, duplicate consolidation, saved range fields, export metadata lookup.
- `backend/app/videos.py`: identity-aware registration, upload hashing, in-memory rename, range-specific tracking caches.
- `backend/app/tracking.py`: local-to-absolute range mapping and range-aware persistence.
- `backend/app/exporter.py`: range-start video decode and matching audio trim/rebase.
- `backend/app/main.py`: API contracts, validation, range propagation, rename/download routes, Library response fields.
- `frontend/src/api.ts`: source-name and frame-range API types/calls.
- `frontend/src/hooks/useWorkspace.ts`: source name, range, stale-selection clearing, saved-player restoration.
- `frontend/src/components/OpenVideoPanel.tsx`: optional source-name input.
- `frontend/src/components/LibraryPanel.tsx`: source rename and player range display.
- `frontend/src/components/VideoStage.tsx`: synchronous pause and playback lock.
- `frontend/src/components/TrackTimeline.tsx`: range handles, Set In/Out, reset, static range display.
- `frontend/src/App.tsx`: range/playback wiring.
- Existing colocated/backend test files cover each changed boundary.

---

### Task 1: Durable source identity and duplicate consolidation

**Files:**
- Modify: `backend/app/library.py`
- Modify: `backend/app/videos.py`
- Test: `backend/tests/test_library.py`
- Test: `backend/tests/test_videos.py`

**Interfaces:**
- Produces: `VideoRecord.source_key: str`
- Produces: `LibraryStore.consolidate_sources(upload_root: Path) -> None`
- Produces: `VideoStore.register_path(raw_path, display_name=None) -> VideoRecord`
- Produces: `VideoStore.register_upload(source, filename=None, display_name=None) -> VideoRecord`
- Produces: `_sha256_file(path: Path) -> str`

- [ ] **Step 1: Write failing registration reuse tests**

Add tests that register `tiny_video` twice by relative/absolute canonical path and assert the same `video_id`, one catalog row, and one in-memory record. Add a multipart/store-level upload test that uploads identical bytes twice and asserts the same ID and exactly one file under `data/uploads/`.

```python
def test_reuses_canonical_path_registration(tmp_path: Path, tiny_video: Path) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    first = store.register_path(tiny_video)
    second = store.register_path(tiny_video.resolve())
    assert second.video_id == first.video_id
    assert len(store.library.videos()) == 1
    assert len(store.records()) == 1


def test_discards_duplicate_uploaded_content(tmp_path: Path, tiny_video: Path) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    with tiny_video.open("rb") as source:
        first = store.register_upload(source, "one.mp4")
    with tiny_video.open("rb") as source:
        second = store.register_upload(source, "two.mp4")
    assert second.video_id == first.video_id
    assert list(store.upload_dir.iterdir()) == [first.path]
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `cd backend && uv run --extra dev pytest tests/test_videos.py -k "reuses_canonical or discards_duplicate" -v`

Expected: both tests fail because registrations currently allocate fresh UUIDs.

- [ ] **Step 3: Implement source keys and registration reuse**

Add `source_key` to `VideoRecord`. Build path keys after `Path.resolve()`. Stream uploads to a temporary file while updating `hashlib.sha256`; look up an existing upload record by digest before moving the temporary file to its final UUID path. When an explicit non-blank name accompanies reuse, call the rename path introduced in Task 2; otherwise preserve the saved name.

```python
@dataclass(frozen=True, slots=True)
class VideoRecord:
    video_id: str
    path: Path
    metadata: VideoMetadata
    frame_cache_dir: Path
    source_kind: str = "path"
    display_name: str | None = None
    source_key: str = ""


def _path_source_key(path: Path) -> str:
    return f"path:{path.resolve()}"


def _upload_source_key(digest: str) -> str:
    return f"sha256:{digest.lower()}"
```

Persist `sourceKey` in `LibraryStore.save_video` and load it during rehydration.

- [ ] **Step 4: Write failing migration tests**

Construct duplicate path rows and duplicate uploaded files with tracks/exports split across IDs. Instantiate `VideoStore` and assert one survivor, all track/export `videoId` references rewritten to the survivor, and only the redundant uploaded file deleted. Add an interrupted-write test by monkeypatching `_write_list` to fail and assert no upload file is deleted.

- [ ] **Step 5: Run migration tests and confirm RED**

Run: `cd backend && uv run --extra dev pytest tests/test_library.py -k "consolidat or duplicate_source" -v`

Expected: failure because no consolidation exists.

- [ ] **Step 6: Implement idempotent consolidation before rehydration**

Call `library.consolidate_sources(self.upload_dir)` in `VideoStore.__init__` before `_rehydrate()`. Determine the survivor by `(openedAt or "", videoId)`. Atomically rewrite track objects, exports, then videos. Delete only duplicate uploaded paths after every rewrite returns successfully and `_is_under` confirms containment. Missing uploads receive no hash and remain unmerged.

- [ ] **Step 7: Verify Task 1 and commit**

Run: `cd backend && uv run --extra dev pytest tests/test_videos.py tests/test_library.py -v`

Expected: PASS.

Commit: `git commit -am "Deduplicate persisted source videos"`

---

### Task 2: Backend source names and readable export filenames

**Files:**
- Modify: `backend/app/library.py`
- Modify: `backend/app/videos.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_videos.py`
- Test: `backend/tests/test_library.py`
- Test: `backend/tests/test_export_api.py`

**Interfaces:**
- Produces: `LibraryStore.rename_video(video_id: str, raw_name: str) -> str | None`
- Produces: `VideoStore.rename(video_id: str, raw_name: str) -> VideoRecord`
- Produces: `PATCH /api/library/videos/{video_id}`
- Produces: `download_filename(source_name: object, player_name: object, width: object, height: object, created_at: object, export_id: object) -> str`

- [ ] **Step 1: Write failing source-name API tests**

Extend video registration tests to send `{path, name}` and multipart `name`, assert `VideoResponse.name`, and assert blank names fall back to the filename. Add PATCH tests for trimmed success, blank/81-character 422, missing 404, and in-memory/catalog consistency.

```python
renamed = client.patch(
    f"/api/library/videos/{video_id}", json={"name": "  Championship Game  "}
)
assert renamed.json() == {"videoId": video_id, "name": "Championship Game"}
assert video_store.get(video_id).name == "Championship Game"
```

- [ ] **Step 2: Run source-name tests and confirm RED**

Run: `cd backend && uv run --extra dev pytest tests/test_videos.py tests/test_library.py -k "name or rename" -v`

Expected: failure because registration responses and video rename do not support source names.

- [ ] **Step 3: Implement source-name validation and API wiring**

Add optional `name` to `VideoPathRequest`, a `name` field from multipart form data, and `name` to `VideoResponse`/`metadata_dict`. Reuse one `_clean_name` rule for trim/blank/80-character validation. Replace the frozen in-memory record with `dataclasses.replace(record, display_name=name)` after the atomic catalog write.

- [ ] **Step 4: Write failing attachment-name tests**

Create a named source and named saved track, save two exports with the same known UTC timestamp but different export IDs, and request each download. Assert RFC-compatible `Content-Disposition` contains names, dimensions, timestamp, and different short-ID suffixes. Include punctuation and legacy missing-name cases.

```python
assert response.headers["content-disposition"].endswith(
    'filename="championship-game-white-19-128x72-20260717-143022-a1b2c3.mp4"'
)
```

- [ ] **Step 5: Run attachment tests and confirm RED**

Run: `cd backend && uv run --extra dev pytest tests/test_export_api.py -k "filename or disposition" -v`

Expected: current response uses `findme-{job_id}.mp4`.

- [ ] **Step 6: Implement deterministic filename construction**

Resolve the export entry by `exportId`, current source catalog entry by `videoId`, and track by `trackJobId`. Sanitize each name to lowercase hyphenated text, retain the `WIDTHxHEIGHT-YYYYMMDD-HHMMSS-SHORTID.mp4` suffix, and cap the total filename without truncating that suffix. Derive `SHORTID` from the final six alphanumeric characters of the unique export ID. Fall back to `source`, `player`, `video`, and the export creation time when legacy fields are absent or invalid.

- [ ] **Step 7: Verify Task 2 and commit**

Run: `cd backend && uv run --extra dev pytest tests/test_videos.py tests/test_library.py tests/test_export_api.py -v`

Expected: PASS.

Commit: `git commit -am "Add source names and export filenames"`

---

### Task 3: Frontend source naming flows

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/api.test.ts`
- Modify: `frontend/src/hooks/useWorkspace.ts`
- Modify: `frontend/src/hooks/useWorkspace.test.tsx`
- Modify: `frontend/src/components/OpenVideoPanel.tsx`
- Modify: `frontend/src/components/OpenVideoPanel.test.tsx`
- Modify: `frontend/src/components/LibraryPanel.tsx`
- Modify: `frontend/src/components/LibraryPanel.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Consumes: registration responses with `VideoMetadata.name`
- Produces: `registerVideo(path: string, name?: string)` and `uploadVideo(file: File, name?: string)`
- Produces: `renameLibrarySource(videoId: string, name: string)`

- [ ] **Step 1: Write failing API and component tests**

Assert path JSON includes `name`, multipart includes a `name` field when non-blank, and rename PATCH targets `/api/library/videos/{id}`. In `OpenVideoPanel.test.tsx`, enter a source name and assert both path and upload callbacks receive it. In `LibraryPanel.test.tsx`, rename a source and assert refresh.

- [ ] **Step 2: Run frontend naming tests and confirm RED**

Run: `cd frontend && npm test -- src/api.test.ts src/components/OpenVideoPanel.test.tsx src/components/LibraryPanel.test.tsx src/hooks/useWorkspace.test.tsx`

Expected: failures from missing name parameters and source rename UI.

- [ ] **Step 3: Implement API types and workspace name state**

```typescript
export interface VideoMetadata {
  videoId: string
  name: string
  width: number
  height: number
  fps: number
  nbFrames: number
  duration: number
}

export async function renameLibrarySource(
  videoId: string,
  name: string,
): Promise<{ videoId: string; name: string }>
```

Use `video.name` as `workspace.videoName` after register/upload and preserve `LibraryVideo.name` when opening saved items.

- [ ] **Step 4: Implement optional open name and Sources inline rename**

Add one `Source name (optional)` input with “Uses the filename when blank.” Pass its trimmed value to either callback. Give Sources separate rename state so it cannot collide with Players rename state. Match existing Save/Cancel/error/busy behavior and 80-character input limit.

- [ ] **Step 5: Verify Task 3 and commit**

Run: `cd frontend && npm test -- src/api.test.ts src/components/OpenVideoPanel.test.tsx src/components/LibraryPanel.test.tsx src/hooks/useWorkspace.test.tsx`

Expected: PASS.

Commit: `git commit -am "Add source naming controls"`

---

### Task 4: Freeze playback during player selection

**Files:**
- Modify: `frontend/src/components/VideoStage.tsx`
- Modify: `frontend/src/components/VideoStage.interaction.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.test.ts`

**Interfaces:**
- Produces: `VideoStageHandle.pause(): void`
- Produces: `VideoStageProps.playbackLocked: boolean`

- [ ] **Step 1: Write failing playback-lock interaction tests**

Test that a playing video is paused before `onSourceClick` and `onCandidateConfirm` execute, `togglePlayback` does not call `play()` while locked, and a native `play` event is immediately paused. Add an App wiring test that text selection calls `videoStageRef.pause()` before the workspace callback.

```typescript
expect(pause.mock.invocationCallOrder[0]).toBeLessThan(
  onSourceClick.mock.invocationCallOrder[0],
)
```

- [ ] **Step 2: Run interaction tests and confirm RED**

Run: `cd frontend && npm test -- src/components/VideoStage.interaction.test.tsx src/App.test.ts`

Expected: pause ordering and lock tests fail.

- [ ] **Step 3: Implement synchronous pause and lock guards**

Pause at the top of click/candidate handlers before reading `currentTime`. Expose `pause()` on the imperative handle. Guard `togglePlayback`; add `onPlay={() => { if (playbackLocked) videoRef.current?.pause() }}`. In App, set the lock when the Select stage has loading, candidates, or a confirmed selection, and wrap text selection with a synchronous `pause()` call.

- [ ] **Step 4: Verify Task 4 and commit**

Run: `cd frontend && npm test -- src/components/VideoStage.interaction.test.tsx src/App.test.ts`

Expected: PASS.

Commit: `git commit -am "Pause video during player selection"`

---

### Task 5: Persist and execute frame-bounded tracking

**Files:**
- Modify: `backend/app/library.py`
- Modify: `backend/app/videos.py`
- Modify: `backend/app/tracking.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_library.py`
- Test: `backend/tests/test_tracking_frame_io.py`
- Test: `backend/tests/test_tracking.py`
- Test: `backend/tests/test_track_api.py`

**Interfaces:**
- Produces: `SavedTrack.start_frame_idx: int` and `end_frame_exclusive: int`
- Produces: `TrackingFrameSequence.start_frame_idx: int`
- Produces: `prepare_tracking_frames(video_id, start_frame_idx=0, end_frame_exclusive=None, frame_limit=None)`
- Produces: `VideoTracker.track(video_id: str, frame_idx: int, box: tuple[int, int, int, int], *, start_frame_idx: int = 0, end_frame_exclusive: int | None = None, on_update: TrackUpdate | None = None) -> list[TrackFrame]`

- [ ] **Step 1: Write failing saved-range and API validation tests**

Save a track with `[100, 140)` and assert JSON/loader/Library response round-trip. Assert omitted fields select full video; invalid/empty/out-of-source ranges and anchors outside the range return 422. Update fake tracker call recording to include the range.

```python
assert tracker.calls == [
    (video_id, 12, (100, 50, 140, 100), 10, 20)
]
```

- [ ] **Step 2: Run persistence/API tests and confirm RED**

Run: `cd backend && uv run --extra dev pytest tests/test_library.py tests/test_track_api.py -k "range or bound" -v`

Expected: missing fields/signatures and no validation.

- [ ] **Step 3: Add range fields with legacy inference**

New track writes always store `startFrameIdx` and `endFrameExclusive`. Loader inference for old non-empty tracks is `min(frame_idx)` and `max(frame_idx) + 1`; expose a full-source fallback in the Library response for empty legacy tracks.

- [ ] **Step 4: Write failing range-cache and local/absolute mapping tests**

Extract frames `[1, 4)` from the four-frame synthetic video and assert exactly three JPEGs plus `sequence.start_frame_idx == 1`. Run a fake propagation returning local indexes `0,1,2` with anchor source frame 2; assert published/persisted indexes `1,2,3`, progress uses three frames, and rescue asks for absolute source frames.

- [ ] **Step 5: Run tracking tests and confirm RED**

Run: `cd backend && uv run --extra dev pytest tests/test_tracking_frame_io.py tests/test_tracking.py -k "range or absolute" -v`

Expected: cache always starts at zero and tracker publishes local indexes.

- [ ] **Step 6: Implement range-specific extraction and mapping**

Use an ffmpeg filter `select=between(n\,START\,END_INCLUSIVE),SCALE` with passthrough frame sync before writing images, and require exactly `end-start` images. Store `start_frame_idx` in `sequence.json` and the cache directory name. Preserve the existing test-only `frame_limit` as a cap from the selected start (`effective_end = min(end_frame_exclusive, start_frame_idx + frame_limit)`). Convert source anchor to `local_anchor = frame_idx - sequence.start_frame_idx`; map every observed local index back before merge, progress, rescue, and missing-frame fill.

- [ ] **Step 7: Wire track route and persistence callback**

Validate bounds against `record.metadata.nb_frames`, pass them into the runner, and capture them in `persist_completed_track`. Keep fake/custom runner compatibility explicit by updating test doubles and the production `VideoTracker` call together.

- [ ] **Step 8: Verify Task 5 and commit**

Run: `cd backend && uv run --extra dev pytest tests/test_library.py tests/test_tracking_frame_io.py tests/test_tracking.py tests/test_track_api.py -v`

Expected: PASS.

Commit: `git commit -am "Track only selected frame ranges"`

---

### Task 6: Export the selected video and audio interval

**Files:**
- Modify: `backend/app/exporter.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_exporter.py`
- Test: `backend/tests/test_export_api.py`

**Interfaces:**
- Consumes: saved track range from Task 5
- Produces: `export_video(source_path: Path, destination: Path, windows: Sequence[CropWindow], *, output_width: int, output_height: int, fps: float, source_start_frame: int = 0, source_total_frames: int | None = None, on_progress: ExportProgress | None = None) -> Path`
- Produces: crop plans whose windows are output-local `0..range_length-1`

- [ ] **Step 1: Write failing subrange video/audio export tests**

Generate a synthetic source with distinguishable frame colors and an audio tone. Export source frames `[8, 24)` at 8 fps. Assert 16 output video frames, first/last colors correspond to source frames 8/23, output begins near PTS zero, audio begins near zero, and audio/video duration is approximately 2 seconds within one audio packet/frame tolerance.

- [ ] **Step 2: Run exporter tests and confirm RED**

Run: `cd backend && uv run --extra dev pytest tests/test_exporter.py -k "subrange or trims_audio" -v`

Expected: current exporter always starts from source frame zero and remuxes full audio.

- [ ] **Step 3: Implement bounded video decode and audio timestamp rebasing**

Skip decoded video frames before `source_start_frame`, pair only the next `len(windows)` frames with zero-based windows, and emit output video PTS `0..N-1`. For partial ranges, decode audio frames intersecting `[start/fps, (start+N)/fps)`, trim boundary samples, rebase timestamps to zero, and encode them as AAC. Retain the existing stream-copy audio path only when `source_start_frame == 0` and `len(windows) == source_total_frames`.

- [ ] **Step 4: Write failing export API range propagation test**

Persist a saved track covering `[1, 4)`, start export, and assert the fake exporter receives `source_start_frame=1`, three windows numbered `0,1,2`, and the saved export remains linked to the same track.

- [ ] **Step 5: Run export API test and confirm RED**

Run: `cd backend && uv run --extra dev pytest tests/test_export_api.py -k "range or source_start" -v`

Expected: source start is not propagated.

- [ ] **Step 6: Make crop/export use the saved track range**

Resolve the persisted `SavedTrack` range (including restored jobs), slice/order absolute track frames for that interval, generate output-local windows, and pass the absolute start to `export_video`. Reject a job/track range mismatch rather than exporting the wrong interval.

- [ ] **Step 7: Verify Task 6 and commit**

Run: `cd backend && uv run --extra dev pytest tests/test_exporter.py tests/test_export_api.py -v`

Expected: PASS.

Commit: `git commit -am "Trim exports to tracked frame ranges"`

---

### Task 7: Interactive timeline range and workspace wiring

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/api.test.ts`
- Modify: `frontend/src/hooks/useWorkspace.ts`
- Modify: `frontend/src/hooks/useWorkspace.test.tsx`
- Modify: `frontend/src/components/TrackTimeline.tsx`
- Modify: `frontend/src/components/TrackTimeline.test.tsx`
- Modify: `frontend/src/components/LibraryPanel.tsx`
- Modify: `frontend/src/components/LibraryPanel.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Produces: `FrameRange { startFrameIdx: number; endFrameExclusive: number }`
- Produces: `TrackTimeline` props `range`, `rangeEditable`, `onRangeChange`
- Consumes: backend tracking/Library range fields

- [ ] **Step 1: Write failing pure range and API tests**

Add `normalizeFrameRange`, `frameRangeCount`, and anchor containment tests in `TrackTimeline.test.tsx` or a focused `frameRange.test.ts`. Assert `startTracking` sends `startFrameIdx` and `endFrameExclusive`; Library track fixtures include both fields.

```typescript
export interface FrameRange {
  startFrameIdx: number
  endFrameExclusive: number
}
```

- [ ] **Step 2: Run range model tests and confirm RED**

Run: `cd frontend && npm test -- src/api.test.ts src/components/TrackTimeline.test.tsx src/hooks/useWorkspace.test.tsx`

Expected: missing types, helpers, and request fields.

- [ ] **Step 3: Implement workspace range state**

Initialize `[0, video.nbFrames)` on open. Expose `setRange`, `setRangeIn`, `setRangeOut`, and `resetRange`. Every range change aborts active selection requests and clears selection/candidates/errors. Reject `selectAt`/candidate/text anchors outside the range. Include range in tracking and atomically restore it with a saved player.

- [ ] **Step 4: Write failing Option A interaction tests**

Render a 1,000-frame timeline at frame 250. Click Set In, seek to 700, click Set Out, and assert `[250, 701)`. Test Reset, pointer handle movement, ArrowLeft/ArrowRight single-frame adjustment, dimmed excluded regions, selected duration/count text, disabled/read-only controls after tracking starts, and stale selection clearing through the workspace.

- [ ] **Step 5: Run timeline interaction tests and confirm RED**

Run: `cd frontend && npm test -- src/components/TrackTimeline.test.tsx src/hooks/useWorkspace.test.tsx`

Expected: current timeline has no range controls.

- [ ] **Step 6: Implement approved timeline handles and controls**

Use two accessible range inputs or pointer-enabled handles with `aria-label="In point"` and `aria-label="Out point"`; keep the underlying values frame-based. Render excluded overlays, the included segment, playhead, progress/lost ranges, absolute timecodes, selected duration, frame count, and Set In/Set Out/Reset buttons. During Review/Export, keep the segment visible but controls disabled.

- [ ] **Step 7: Show saved ranges in Library and wire App**

Pass range state/current frame/editability into `TrackTimeline`, pass the selection lock into `VideoStage`, and show player rows as `MM:SS–MM:SS · DURATION · N frames`. Keep full-video legacy records readable.

- [ ] **Step 8: Verify Task 7 and commit**

Run: `cd frontend && npm test -- src/api.test.ts src/components/TrackTimeline.test.tsx src/components/LibraryPanel.test.tsx src/hooks/useWorkspace.test.tsx src/App.test.ts`

Expected: PASS.

Commit: `git commit -am "Add frame range controls to the timeline"`

---

### Task 8: Regression, real-flow, review, and deployment readiness

**Files:**
- Modify only files required by failures found in this task.

**Interfaces:**
- Consumes all prior tasks.
- Produces a verified production bundle and evidence for deployment.

- [ ] **Step 1: Run the backend weight-free suite**

Run: `cd backend && uv run --extra dev pytest -m "not integration"`

Expected: all unmarked tests pass; model/GPU integration tests remain deselected or skip cleanly.

- [ ] **Step 2: Run frontend tests and production build**

Run: `cd frontend && npm test && npm run build`

Expected: all Vitest files pass and Vite writes `frontend/dist` successfully.

- [ ] **Step 3: Run static repository checks**

Run: `git diff --check && git status --short`

Expected: no whitespace errors and only intentional changes before the final commit.

- [ ] **Step 4: Exercise the real HTTP flow when `examples/example.mp4` exists**

Register the same path twice and verify one ID; rename it; choose a short range containing the anchor; click-select; track; export; download. Verify:

```bash
ffprobe -v error -show_entries stream=index,codec_type,duration,nb_frames -show_entries format=duration -of json exported-range.mp4
```

Expected: video frame count equals `end-start`, duration matches that count/fps, audio is bounded to the same interval, excluded frames are absent, and `Content-Disposition` follows the approved source/player/resolution/timestamp/short-ID format.

- [ ] **Step 5: Perform visual checks**

Open the production UI, verify source reuse/rename, Option A handle behavior, selection freeze/overlay alignment, saved range restoration, Library range copy, and readable download name. Do not mutate unrelated live Library data.

- [ ] **Step 6: Review implementation against the spec**

Use `superpowers:requesting-code-review`. Resolve any correctness issues with a new failing test before implementation changes, then rerun the affected suite.

- [ ] **Step 7: Final verification and commit**

Repeat Steps 1–3 after review fixes. Commit intentional remaining changes with an imperative subject, then use `superpowers:finishing-a-development-branch` before merge/push/deploy.
