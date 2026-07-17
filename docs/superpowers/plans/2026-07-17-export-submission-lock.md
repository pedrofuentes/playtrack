# Export Submission Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent export submission from racing source switches, duplicate starts, stale component continuations, and destructive UI actions.

**Architecture:** `useWorkspace` owns a ref-backed numeric export-start token and includes it in `videoSwitchLocked`. `ExportPanel` acquires/releases that token and guards every post-await/socket continuation with a mounted request generation. App passes the same active-job lock to Library and Settings destructive controls.

**Tech Stack:** React 19, TypeScript, Vitest/jsdom, Vite.

## Global Constraints

- Do not modify backend lifecycle code.
- Preserve selection/open/tracking mutual exclusion and Task 6 `sourceStartFrame` wiring.
- Only the owning export token may release export-start state.
- Do not invoke branch finishing or integration workflows.

---

### Task 1: Workspace-owned export start token

**Files:**
- Modify: `frontend/src/hooks/useWorkspace.ts`
- Test: `frontend/src/hooks/useWorkspace.test.tsx`

**Interfaces:**
- Produces: `exportStarting: boolean`.
- Produces: `beginExportSubmission(): number | null`.
- Produces: `finishExportSubmission(token: number): void`.

- [ ] **Step 1: Write the failing token/open tests**

Add a controller test that claims a token, immediately calls `openPath`, and
asserts registration is not called while `exportStarting` and
`videoSwitchLocked` are true. Assert a second claim returns null, a wrong token
cannot unlock, the owning token unlocks, and a new token can be claimed for
retry.

- [ ] **Step 2: Run RED**

```bash
cd frontend && npm test -- --run src/hooks/useWorkspace.test.tsx
```

Expected: controller has no export submission fields/actions and source open is
not synchronously blocked.

- [ ] **Step 3: Implement the token**

Use `exportSubmissionRef: MutableRefObject<number | null>`, a monotonically
increasing counter, and React `exportStarting` state. Claim synchronously before
`setExportStarting(true)`; release only on token equality. Include state in
`videoSwitchLocked`, and include the ref directly in both source-open guards.

- [ ] **Step 4: Run GREEN**

Run the Step 2 command and require all workspace tests to pass.

### Task 2: Generation-safe ExportPanel

**Files:**
- Modify: `frontend/src/components/ExportPanel.tsx`
- Test: `frontend/src/components/ExportPanel.interaction.test.tsx`
- Update fixture: `frontend/src/components/ExportPanel.test.tsx`
- Modify: `frontend/src/App.tsx`
- Update fixture: `frontend/src/App.test.ts`

**Interfaces:**
- Consumes: `exportStarting`, `beginExportSubmission`, and
  `finishExportSubmission` from Task 1.
- ExportPanel props: `exportStarting: boolean`,
  `onExportStart: () => number | null`, and
  `onExportFinish: (token: number) => void`.

- [ ] **Step 1: Write deferred lifecycle tests**

Mock `startExport` and `watchTrackJob`. After preview readiness, start twice in
one tick and assert one start request. Unmount before a deferred start resolves,
clear initial callback history, resolve it, and assert no queued job callback,
socket, or Library refresh occurs and only the owning token was released. Reject
the first request, assert its token is released, retry with a second token, and
assert the second request starts.

- [ ] **Step 2: Run RED**

```bash
cd frontend && npm test -- --run src/components/ExportPanel.interaction.test.tsx src/components/ExportPanel.test.tsx src/App.test.ts
```

Expected: duplicate `startExport`, stale post-unmount queued/socket callbacks,
and missing required workspace lock props/wiring.

- [ ] **Step 3: Implement request ownership**

Replace local export-start state with the workspace prop. Store the active token
and current request generation in refs. Every post-await update, WebSocket
callback, and Library callback must first check mounted/current generation.
Unmount increments generation, closes the socket, and releases the active token
once. `finally` releases only when it still owns the active token. Wire App to
the workspace actions/state.

- [ ] **Step 4: Run GREEN**

Run the Step 2 command and require all tests to pass without act warnings or
unhandled continuations.

### Task 3: Active-job destructive controls

**Files:**
- Modify: `frontend/src/components/LibraryPanel.tsx`
- Test: `frontend/src/components/LibraryPanel.test.tsx`
- Modify: `frontend/src/components/SettingsPanel.tsx`
- Create: `frontend/src/components/SettingsPanel.test.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/App.test.ts`

**Interfaces:**
- LibraryPanel prop: `destructiveDisabled?: boolean`.
- SettingsPanel prop: `disabled?: boolean`.
- App passes `workspace.videoSwitchLocked` to both.

- [ ] **Step 1: Write component and integration tests**

Render LibraryPanel with `destructiveDisabled`; assert source/player/export
delete and rename actions are disabled. Render SettingsPanel disabled; assert
Clear frame cache is disabled and does not confirm/call. Render App with an
active workspace lock and assert Library rename/delete and Settings clear are
disabled.

- [ ] **Step 2: Run RED**

```bash
cd frontend && npm test -- --run src/components/LibraryPanel.test.tsx src/components/SettingsPanel.test.tsx src/App.test.ts
```

Expected: missing props and enabled destructive buttons.

- [ ] **Step 3: Implement UI locks**

Disable Library remote rename/save and all delete buttons when busy or
`destructiveDisabled`; leave local tab/search/cancel usable. Guard Settings
`clear()` and disable its button when busy or `disabled`. Pass the shared lock
from App.

- [ ] **Step 4: Run GREEN**

Run the Step 2 command and require all tests to pass.

### Task 4: Verification and commit

**Files:**
- Modify: `.superpowers/sdd/task-7-report.md`

- [ ] **Step 1: Run focused export/workspace/UI tests**

Run the affected hook, ExportPanel, LibraryPanel, SettingsPanel, and App tests.

- [ ] **Step 2: Run full frontend and build**

Run `npm test` and `npm run build` from `frontend`; require zero failures.

- [ ] **Step 3: Verify scope/invariants**

Run `git diff --check`, confirm no backend files are modified, and grep
`sourceStartFrame`, `loadingRef`, `trackStartingRef`, and the new export token.

- [ ] **Step 4: Update report and commit**

Record RED/GREEN and exact verification counts. Stage only intended frontend
and planning files, then commit with an imperative subject.
