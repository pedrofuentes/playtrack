# Selection frame and range-display review fixes

**Date:** 2026-07-17

## Scope

Resolve whole-feature review findings around click-selection frame identity,
out-point display, and the Library metadata contract without changing
tracking/export semantics or the existing synchronous open/tracking exclusion.

## Selection-frame freeze

Click selection uses one exact source frame from pointer input through the SAM 2
request. `VideoStage` pauses the media element before reading coordinates,
derives the displayed frame from current media time, records it as the frozen
frame, and passes both the source point and frame index to the workspace. This
avoids relying on potentially lagging React `currentFrame` state.

While selection is loading or a selection is confirmed, all frame mutation is
blocked. Keyboard stepping, imperative stepping/seeking, and native media
scrubbing leave the media at the frozen frame. Native media events restore the
frozen time and report the frozen frame rather than allowing overlays to drift
onto another frame. Releasing the selection clears the freeze.

## Range validation and display

`VideoStage` remains locked for workspace operations and non-Select stages, but
an otherwise valid click outside the selected range reaches workspace
validation. The workspace shows its existing inline “Choose a frame inside the
selected range” error and does not issue a selection request.

Ranges remain half-open for all computation and API payloads. Human-facing Out
timestamps use the final included frame, `endFrameExclusive - 1`. Selected
duration remains `frameCount / fps`; no frame is removed from export or
tracking. This rule applies to both TrackTimeline and saved-player Library copy.

## Library metadata contract

The backend Library response intentionally nests technical video metadata
without a display name; the saved source name is a top-level Library field.
Frontend types model that shape with a dedicated name-less Library metadata
type. When a saved source/player becomes the active workspace video, the
workspace constructs `VideoMetadata` by combining nested technical metadata
with the top-level saved name.

## Verification

Regression coverage includes media time ahead of React state, click callback
frame identity, keyboard and imperative navigation, native seeking events, an
outside-range click reaching inline validation, low-fps inclusive Out labels,
and a Library response fixture whose nested metadata omits `name`. Run the
focused frontend tests specified in implementation Tasks 1–4, full frontend
suite, production build, and diff checks, and record the results in the
verification report. Backend code is not expected to change, so the backend
gate is not required unless implementation scope expands.
