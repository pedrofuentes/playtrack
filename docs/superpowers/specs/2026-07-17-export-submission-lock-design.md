# Export submission lock design

## Scope

Close the frontend race between export submission, source switching, duplicate
submission, component unmount, and destructive Library/Settings actions. Backend
job lifecycle changes are explicitly out of scope.

## Workspace lock

The workspace owns export-start state. `beginExportSubmission()` synchronously
claims a monotonically increasing numeric token in a ref before updating React
state. It returns `null` if another export submission already owns the lock.
`finishExportSubmission(token)` releases state only when that exact token still
owns the ref. `videoSwitchLocked` includes export starting as well as queued and
running track/export jobs, and source-open guards read the token ref directly so
an open attempted in the same tick is rejected.

## ExportPanel request ownership

ExportPanel receives the workspace start/finish callbacks and the starting state
for UI. Each accepted start increments a mounted request generation and stores
its workspace token. Duplicate activation cannot acquire another token. After
`startExport` resolves or rejects, all state/callback/socket/library work checks
that the component is mounted and the generation is still current.

Unmount invalidates the generation, closes the socket, and releases the active
starting token once. A later stale continuation cannot install a queued job,
attach a WebSocket, refresh the Library, or release a newer token. Failure
releases its own token and leaves the panel retryable.

## Destructive UI lock

App passes the same workspace active-job lock to LibraryPanel and SettingsPanel.
Library source/player/export delete actions and remote rename actions are
disabled during tracking/export starting, queued, or running. Settings disables
frame-cache clearing for the same interval. Existing source-open disabling
continues to include workspace loading.

## Verification

Tests use deferred export submission to cover same-tick source open, duplicate
start, unmount before resolution, stale continuation suppression, failure
release, and retry. Component/integration tests cover Library and Settings
destructive controls. Run focused frontend tests, the full frontend suite,
production build, and diff checks. Do not run backend tests because backend files
must not change.
