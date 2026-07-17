# Source Identity, Naming, and Selection Lock Design

**Date:** 2026-07-17

## Goal

Make each source video appear once in the Library, let users name sources when opening them or later, freeze playback while a player selection is active, and give exported downloads readable, unique filenames derived from the source and player names.

## Scope

This change covers source registration and migration, source naming, selection-time playback behavior, and download filenames. It does not change tracking, crop planning, encoded export contents, or the existing source/player/export Library tabs.

## User Experience

### Source registration and naming

- Opening a server path or uploading a file may include an optional source name.
- A blank source name defaults to the original filename.
- Reopening the same canonical server path returns the existing source instead of creating another Library entry.
- Re-uploading byte-identical media returns the existing uploaded source and discards the newly received duplicate copy.
- The Sources tab supports inline rename with the same interaction pattern as player rename.
- Source names are trimmed, must contain at least one non-whitespace character when explicitly renamed, and are limited to 80 characters.
- Reusing an existing source does not overwrite its current name unless the request includes a non-blank explicit name.

Server-path and uploaded sources retain different ownership semantics. Registered paths deduplicate by canonical resolved path. Uploads deduplicate by SHA-256 content digest. The system does not collapse a registered path and an uploaded copy into one source, even when their bytes match, because only uploaded files may be deleted by FindMe.

### Player selection playback

- Users may play or scrub footage to find an anchor frame before starting selection.
- A click selection pauses the video synchronously before the frame index is captured.
- Starting text selection also pauses the video before the request is sent.
- Playback remains locked while click/text selection is loading, while text candidates are shown, or while a player selection is confirmed.
- Native controls and the Space shortcut cannot resume playback while locked.
- Resetting the selection removes the lock but does not automatically resume playback.
- Tracking and later review/export stages keep their current playback behavior.

This makes the selected box and mask refer to the frame that remains on screen.

### Download filenames

The server supplies a deterministic attachment filename for every completed export:

`<source>-<player>-<width>x<height>-<YYYYMMDD-HHmmss>.mp4`

Example:

`championship-game-white-19-1920x1080-20260717-143022.mp4`

The timestamp is the export creation time in UTC, so two exports with otherwise identical names and dimensions remain distinguishable. Source and player segments use their latest saved names at download time. Segments are trimmed, converted to filesystem-safe hyphenated text, stripped of leading/trailing punctuation, and fall back to `source` or `player` for legacy records. The complete attachment name is capped to a practical length while preserving the resolution, timestamp, and `.mp4` suffix.

## Backend Design

### Persisted source identity

Each video catalog entry gains an optional `sourceKey`:

- Registered path: `path:<canonical-absolute-path>`
- Uploaded media: `sha256:<lowercase-hex-digest>`

`VideoRecord` carries the persisted display name and source key. `VideoStore.register_path` resolves the path, computes its path key, and returns the matching record if present. `VideoStore.register_upload` hashes bytes while receiving the upload into a temporary file; when the digest matches an existing uploaded record, it deletes only the temporary duplicate and returns the existing record. A new upload is moved into its final UUID-based location only after no match exists.

The registration API accepts an optional name in the JSON body for paths and as a multipart form field for uploads. `VideoResponse` includes the resolved source name so the editor title updates immediately.

### Existing-data migration

Startup performs an idempotent migration before normal rehydration:

1. Build canonical path keys for registered paths and SHA-256 keys for uploaded files that still exist.
2. Group entries by `(sourceKind, sourceKey)` and choose the earliest `openedAt`, then lexicographically smallest `videoId`, as the survivor.
3. Atomically rewrite every duplicate track JSON to the survivor `videoId`.
4. Atomically rewrite export catalog references to the survivor `videoId`.
5. Atomically rewrite the video catalog with one survivor per group and its `sourceKey`.
6. Delete redundant uploaded files only after all catalog/reference rewrites succeed, and only when they are underneath `data/uploads/` and are not the survivor path.

This order is deliberately recoverable. If interrupted before the catalog rewrite, rerunning the migration completes consolidation. It never deletes registered-path media or a survivor upload. All player and export records are preserved; their user-provided names are not altered.

Missing media entries cannot be fingerprinted. Registered paths still receive their canonical path key and can be consolidated. Missing uploads remain separate rather than risking an incorrect merge.

### Rename API

Add `PATCH /api/library/videos/{video_id}` with `{ "name": string }`. It validates the cleaned name, updates the persisted catalog atomically, updates the in-memory immutable `VideoRecord`, and returns `{ "videoId": string, "name": string }`. A missing source returns 404; blank or overlong names return 422.

### Export attachment lookup

The export download route resolves the saved export record, its source, and its saved track. It constructs the `Content-Disposition` filename from current names, saved dimensions, and `createdAt`. Legacy or incomplete records use safe fallbacks. Export storage paths remain UUID/job-ID based, so renaming never moves encoded files or breaks links.

## Frontend Design

### API types and calls

- Add `name` to `VideoMetadata`.
- Let `registerVideo` and `uploadVideo` accept an optional source name.
- Add `renameLibrarySource(videoId, name)`.
- Keep download URLs stable; browsers receive the readable filename from the server response.

### Open and Library interfaces

The open-video UI adds an optional `Source name` field shared by path and upload flows, with copy explaining that the filename is used when blank. The editor uses the returned name immediately. Sources gain inline Rename, Save, and Cancel controls matching the existing Players tab pattern.

### Selection lock boundary

`VideoStage` owns the synchronous media action because it has direct access to the `<video>` element. Its imperative handle gains `pause()`. Click and candidate confirmation handlers pause before reading `currentTime`. App pauses the stage before invoking text selection. A `playbackLocked` prop prevents native play events and shortcut playback while selection state is active. This keeps media control separate from asynchronous selection state in `useWorkspace`.

## Error Handling

- Duplicate registration returns the existing source as a normal successful response.
- If upload hashing or registration fails, only the temporary upload is removed.
- A migration write failure stops before redundant upload deletion; the next startup retries.
- Source rename failures remain visible inside the Library and leave the old name intact.
- Invalid legacy timestamps or dimensions produce a safe fallback download name rather than blocking the download.

## Testing

### Backend

- Registering the same canonical path twice returns the same ID and one catalog entry.
- Registering equivalent relative, absolute, and symlink-resolved paths reuses the source.
- Uploading identical bytes twice returns the same ID and leaves one stored upload.
- Explicit names persist; blank names use filenames; reusing without a name preserves the current name.
- Startup migration merges duplicate path/upload entries, rewrites track and export references, preserves all records, and removes only redundant uploaded files.
- Source rename validates input and updates both API responses and in-memory records.
- Download responses produce sanitized source/player/resolution/timestamp filenames and distinguish same-named exports by creation time.

### Frontend

- Path and upload registration submit optional source names and consume the returned name.
- The Sources tab renames a source inline and refreshes the Library.
- Clicking a player pauses before the selection callback observes the frame.
- Text selection pauses before the API request.
- Native and shortcut playback remain blocked until selection is reset.
- Existing review/export playback controls continue to work.

### Completion gate

Run the backend weight-free suite, the full frontend test suite, and the production frontend build. Exercise registration reuse, source rename, selection pause, tracking/export, and the download `Content-Disposition` header through the HTTP API with `examples/example.mp4` when the local asset is available. Inspect the exported file with `ffprobe` and visually verify that the frozen selection overlay remains aligned.
