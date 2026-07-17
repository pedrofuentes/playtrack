# Player Library and Adaptive Framing Design

## Summary

FindMe will present persisted tracks as named players, separate source footage,
players, and finished exports into distinct Library views, and restore saved
players into the same Review experience as newly completed tracking. Camera
smoothness will become visibility-safe: the crop widens before smoothing can
leave the tracked player outside the frame, then eases back to the requested
zoom.

## Named players and Library

The durable track remains the backend primitive, with a new `name` field. The
selection inspector offers an optional player name before tracking. Blank names
are allocated as the first unused `Player N` for that source; explicit names are
trimmed, limited to 80 characters, and may duplicate another explicit name.
Legacy tracks are backfilled once in creation order with crash-safe writes.

Library has three tabs:

- **Sources** lists registered or uploaded source footage with Open and Delete.
- **Players** lists name, source, health, date, Open player, Rename, and Delete.
- **Exports** lists the player and source plus render metadata, Download, and
  Delete. It does not offer a misleading Re-export action.

Open player restores the track at its anchor frame in Review. Export creation
always proceeds from Review through Adjust framing. Existing deletion cascades
remain unchanged.

## Adaptive framing

The requested zoom is the desired close framing. Each planned frame uses the
tracked box to keep the full player inside an inner 80% safe area. When needed,
the crop widens immediately while preserving output aspect ratio. It returns to
the desired zoom with a 0.75-second time constant. At the 1x limit, the center
moves the minimum distance necessary to contain the player. Lost frames keep
the latest safe scale and the interpolated pan path; reacquisition can widen
immediately. Final windows remain even and source-clamped.

Preview and export continue to use the same crop plan. `CropWindow` already
supports per-frame dimensions, and the exporter already resizes variable-size
windows to the fixed output resolution.

## Restore and overlays

Saved-player restoration loads and validates a completed track before changing
editor state. Failure leaves the current editor untouched and visible feedback
in Library; the drawer closes only after success. A single playback-synchronized
overlay component draws the tracked-player and crop layers so fresh and restored
tracks share one clock for play, pause, seek, scrub, resize, and canvas zoom.
Review shows the player box. Framing shows both the player and adaptive crop.

## Interfaces and compatibility

- `POST /api/track` accepts optional `playerName` and returns `jobId` plus the
  resolved `playerName`.
- `GET /api/library` adds `name` to track records without restructuring the
  existing response.
- `PATCH /api/library/tracks/{job_id}` accepts `{ "name": "..." }` and returns
  `{ "jobId": "...", "name": "..." }`.
- The crop planner accepts boxes aligned with centers; HTTP crop-plan and export
  request/response shapes remain compatible.

## Verification

Backend tests cover name allocation/migration/rename, persistence, cascades,
adaptive containment, easing, loss, source edges, and even dimensions. Frontend
tests cover tab separation, active-tab search, naming, rename, atomic restore,
failure retention, and synchronized playback overlays. The saved 3.4x/1.2s
930-frame case must go from 130 containment violations to zero. Both full suites
and the production build remain required gates.
