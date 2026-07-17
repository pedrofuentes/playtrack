# Selection frame and range-display review fixes

## Scope

Resolve whole-feature review findings around selection-frame identity, out-point
display, and the Library metadata contract without changing tracking/export
semantics or the existing synchronous open/tracking exclusion.

## Selection-frame freeze

Selection uses one exact source frame from start through candidate confirmation.
`VideoStage.pause()` pauses the media element, derives the displayed frame from
its current media time, reports that frame to workspace state, records it as the
frozen frame, and returns it to the caller. Text selection passes this returned
frame explicitly to the workspace instead of relying on potentially lagging
React `currentFrame` state. Click selection uses the same pause-and-freeze path.

While selection is loading, candidates are visible, or a selection is confirmed,
all frame mutation is blocked. Keyboard stepping, imperative stepping/seeking,
and native media scrubbing leave the media at the frozen frame. Native media
events restore the frozen time and report the frozen frame rather than allowing
overlays to drift onto another frame. Releasing the selection clears the freeze.

Text candidates remain associated with the frame used by the grounding request.
Candidate confirmation succeeds only when the clicked displayed frame matches
the stored candidate frame; a mismatch is rejected without installing a
selection.

## Range validation and display

VideoStage remains locked for workspace operations and non-Select stages, but an
otherwise valid click outside the selected range reaches workspace validation.
The workspace shows its existing inline "Choose a frame inside the selected
range" error and does not issue a selection request.

Ranges remain half-open for all computation and API payloads. Human-facing Out
timestamps use the final included frame, `endFrameExclusive - 1`. Selected
duration remains `frameCount / fps`; no frame is removed from export or tracking.
This rule applies to both TrackTimeline and saved-player Library copy.

## Library metadata contract

The backend Library response intentionally nests technical video metadata
without a display name; the saved source name is a top-level Library field.
Frontend types model that shape with a dedicated name-less Library metadata type.
When a saved source/player becomes the active workspace video, the workspace
constructs `VideoMetadata` by combining nested technical metadata with the
top-level saved name.

## Verification

Regression coverage will include media time ahead of React state, keyboard and
imperative navigation, native seeking events, candidate-frame mismatch, an
outside-range click reaching inline validation, low-fps inclusive Out labels,
and a Library response fixture whose nested metadata omits `name`. Run the
focused Task 7 frontend tests, full frontend suite, production build, and diff
checks. Backend code is not expected to change, so the backend gate is not
required unless implementation scope expands.
