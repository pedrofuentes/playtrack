# M1 Click-to-Select Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add high-resolution click-prompted SAM 2.1 player selection with a source-aligned frontend mask and box.

**Architecture:** Pure geometry computes a clamped 1024×1024 source crop, `VideoStore` caches that exact crop, and an injectable selector translates between crop and source space. A lazy singleton SAM 2 engine owns official image-predictor loading and device contexts; the frontend posts the current frame click and aligns a full-source transparent mask with the existing contained-video geometry.

**Tech Stack:** Python 3.11/3.12, FastAPI, ffmpeg, PyTorch, SAM 2.1, NumPy, Pillow, OpenCV, React, TypeScript, Vitest.

## Global Constraints

- Implement M1 only; the Track button must not start tracking.
- Run SAM on a source-pixel crop of at most 1024×1024, not the full downscaled panorama.
- Keep Torch, NumPy, Pillow, and SAM imports lazy so weight-free tests run in the existing M0 environment.
- Use SAM 2.1 base-plus as the configured and download default.
- Do not download packages or checkpoints and do not bind ports in this sandbox.

---

### Task 1: Pure selection geometry and source crop I/O

**Files:**
- Create: `backend/app/selection.py`
- Modify: `backend/app/videos.py`
- Create: `backend/tests/test_selection_geometry.py`

**Interfaces:**
- Produces: `CropWindow`, `compute_crop_window`, `source_to_crop_point`, `crop_box_to_source`, and `VideoStore.extract_source_crop(video_id, frame_idx, x, y, width, height)`.

- [ ] Write tests proving a centered pano crop is `(1536, 0, 1024, 1024)`, edge crops clamp, small frames use their full dimensions, points become crop-local, and XYXY boxes translate back to source space.
- [ ] Run `UV_CACHE_DIR=/tmp/findme-uv-cache uv run --frozen --extra dev pytest tests/test_selection_geometry.py -q` and verify imports/functions fail because M1 geometry is absent.
- [ ] Implement immutable crop geometry and exact ffmpeg PNG crop caching under `data/selection-crops`.
- [ ] Re-run the focused tests and the M0 backend suite.

### Task 2: Device profiles and lazy SAM 2 image engine

**Files:**
- Create: `backend/app/models/__init__.py`
- Create: `backend/app/models/sam2_engine.py`
- Create: `backend/tests/test_sam2_engine.py`
- Modify: `backend/app/config.py`

**Interfaces:**
- Produces: `DeviceProfile`, `detect_device`, `SAM2Prediction`, `SAM2Engine.predict`, and singleton `get_sam2_engine`.

- [ ] Write fake-Torch tests for CUDA Turing fp16/base-plus, CUDA Ampere bf16/large, MPS fp32/base-plus, CPU fp32/small, and singleton identity.
- [ ] Run the focused tests and verify RED due to the missing engine module.
- [ ] Implement dependency-free module import, lazy official builder/predictor imports, highest-score multimask selection, device-specific inference contexts, and predictor locking.
- [ ] Re-run the focused tests without installing Torch or SAM.

### Task 3: Click selector and FastAPI contract

**Files:**
- Modify: `backend/app/selection.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_select_api.py`
- Create: `backend/tests/test_sam2_integration.py`

**Interfaces:**
- Produces: `ClickSelection`, `ClickSelector.select_click`, `POST /api/select/click`, and response `{box, maskPng, score}`.

- [ ] Write an API test with an injected fake selector and a checkpoint-gated integration test against `examples/example.mp4`.
- [ ] Run the API test and verify RED because the route and injection point are absent.
- [ ] Implement validation, lazy runtime image/mask imports, full-source transparent PNG encoding, route models, and 404/422/503 mapping.
- [ ] Re-run all non-integration backend tests; collect the integration test and confirm it skips with no checkpoint.

### Task 4: Model downloader and dependency declaration

**Files:**
- Create: `scripts/fetch_models.py`
- Modify: `backend/pyproject.toml`

**Interfaces:**
- Produces: CLI flags `--model`, `--all`, `--output-dir`, `--force`; default output `checkpoints/sam2.1_hiera_base_plus.pt`.

- [ ] Add the four official Meta checkpoint URLs and atomic standard-library download implementation.
- [ ] Declare Torch, TorchVision, official SAM-2 Git source, NumPy, Pillow, and OpenCV-headless dependencies without attempting resolution in this sandbox.
- [ ] Run Python compilation and `scripts/fetch_models.py --help` only.

### Task 5: Frontend request and source-aligned result overlay

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/geometry.ts`
- Modify: `frontend/src/geometry.test.ts`
- Create: `frontend/src/api.test.ts`
- Modify: `frontend/src/components/VideoStage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Produces: `ClickSelection`, `selectByClick`, `displayedFrameIndex`, `canvasRectFromSourceBox`, and M1 selection UI.

- [ ] Write failing tests for the bare-integer click route/body, frame-index clamping, and letterbox-aware box projection.
- [ ] Run focused Vitest and verify RED because the client/geometry functions are absent.
- [ ] Implement request cancellation, loading/error state, transparent mask image, canvas source box, and Track stub.
- [ ] Run all frontend tests, typecheck, and build.

### Task 6: Final M1 verification and audit

**Files:** No production changes expected.

- [ ] Run all weight-free backend tests with the existing frozen environment and verify the integration test skips.
- [ ] Run all frontend tests, TypeScript typecheck, and production build.
- [ ] Run `python -m compileall`, `git diff --check`, downloader help, and a line-by-line M1 deliverable audit.
- [ ] Confirm M2 tracking modules/endpoints remain absent.
