# PlayTrack — Player-Tracking Virtual Camera App

> Historical roadmap, rebranded from the project's original FindMe plan. It records the
> M0–M5 design decisions that led to the current implementation; `README.md` and
> `AGENTS.md` are authoritative for current commands, configuration, and architecture.

## Context

Pedro wants a Windows app where you open a sports video, click a player to select them, the app tracks that player across the video, and exports a cropped video that follows the player at user-chosen output dimensions. The test asset is a **4096×1024, 30 fps, 31 s (930 frames) panoramic match video** — the classic "virtual camera over a panorama" use case (Veo/Pixellot style).

This document is the roadmap + implementation spec **to be executed by Codex**. The test video lives at `examples/example.mp4`.

### Key research findings that shaped the design

- **SAM 2.1** (Meta, Apache 2.0) is a promptable **video** segmentation model: click/box on one frame → mask propagated across all frames (streaming memory attention). Runs on CUDA, MPS, and CPU.
- **Decision (confirmed with Pedro): one-model pipeline.** A high-resolution click crop gives SAM 2 a useful image prompt even when the player is tiny in the panorama; SAM 2 then handles frame-to-frame tracking.
- **Target hardware: Windows + RTX 2080 Ti (Turing, 11 GB).** Constraints: no native bf16 and no FlashAttention-2 on Turing, so the default is the SAM 2.1 **base-plus** checkpoint in **fp16** with **SDPA** attention.
- **Dev machine is a Mac** → selection, tracking, and export must also run on MPS/CPU.

## Architecture

```
┌────────────────────────────┐        HTTP + WebSocket        ┌─────────────────────────────┐
│ frontend/  (TypeScript)    │ ─────────────────────────────► │ backend/  (Python 3.11/3.12)│
│ React + Vite               │                                │ FastAPI + uvicorn           │
│ - <video> player + canvas  │   /api/videos, /api/select,    │ - VideoStore (probe/frames) │
│   overlay (click, boxes,   │   /api/track, /api/export,     │ - Selector: SAM2 image      │
│   track path, crop preview)│   /ws/jobs/{id}                │   predictor                 │
│ - export dims / zoom /     │                                │ - Tracker: SAM2 video       │
│   smoothing controls       │                                │   propagation + loss checks│
│                            │                                │ - CropPlanner: smoothing    │
└────────────────────────────┘                                │ - Exporter: PyAV crop+encode│
                                                              └─────────────────────────────┘
```

Single-user localhost app. One command starts the backend, which serves the built frontend; dev mode runs Vite separately with a proxy.

### Repo layout

```
PlayTrack/
├── docs/plan.md                  # this spec (committed for Codex)
├── examples/example.mp4          # moved from repo-root `example`
├── backend/
│   ├── pyproject.toml            # uv-managed; torch, sam2, fastapi, av, opencv-python-headless, pillow, numpy, websockets
│   ├── app/
│   │   ├── main.py               # FastAPI app, static serving, CORS (dev)
│   │   ├── config.py             # device autodetect (cuda→fp16/sdpa on Turing, bf16 on Ampere+; mps; cpu) and model paths
│   │   ├── videos.py             # register/upload, ffprobe metadata, frame extraction cache, poster frames
│   │   ├── selection.py          # click→SAM2 image mask on a high-resolution source crop
│   │   ├── tracking.py           # SAM2 video propagation job; per-frame box/centroid; loss detection
│   │   ├── crop_planner.py       # trajectory smoothing + crop-window path (pure functions, no torch)
│   │   ├── exporter.py           # PyAV: decode→crop→resize→encode h264 + copy source audio
│   │   ├── jobs.py               # in-memory job registry, progress via WebSocket
│   │   └── models/
│   │       └── sam2_engine.py    # lazy singleton: image predictor + video predictor, device/dtype handling
│   └── tests/                    # pytest: crop_planner unit tests, API tests with tiny synthetic video
├── frontend/
│   ├── package.json              # react, typescript, vite
│   └── src/
│       ├── App.tsx               # layout: player, sidebar controls, timeline
│       ├── api.ts                # typed client + WS job progress hook
│       ├── components/VideoStage.tsx   # <video> + <canvas> overlay; click coords → source-pixel coords
│       ├── components/TrackOverlay.tsx # draw per-frame box + crop-window rectangle synced to currentTime
│       └── components/ExportPanel.tsx  # W×H presets (1920×1080, 1280×720, custom), zoom, smoothing, progress, download
├── scripts/
│   ├── dev.sh / dev.ps1          # run backend (uv) + frontend (vite) together
│   └── fetch_models.py           # download SAM2.1 checkpoints
└── README.md                     # setup for Mac (dev) and Windows/2080 Ti (full)
```

### API surface

- `POST /api/videos` — body `{path}` (local file, e.g. examples/example.mp4) or multipart upload → `{videoId, width, height, fps, nbFrames, duration}`; video then served at `GET /api/videos/{id}/file` with Range support so the browser `<video>` plays it natively.
- `POST /api/select/click` — `{videoId, frameIdx, x, y}` (source pixels) → SAM2 image predictor on that frame → `{box, maskPng (base64), score}` for instant visual confirmation.
- `POST /api/track` — `{videoId, frameIdx, box}` → starts job → `{jobId}`. Result: `{track: [{frameIdx, box|null, center|null, lost}]}` (null while target absent).
- `POST /api/export` — `{videoId, jobId(track), outWidth, outHeight, zoom, smoothing:{windowSec, deadZonePx, maxVelPxPerFrame}}` → export job → `{jobId}`; done → `GET /api/exports/{id}.mp4`.
- `WS /ws/jobs/{jobId}` — `{state, progress: 0..1, message}` stream; also used to stream partial track results so the overlay fills in live.

### Core algorithms

**Tracking (tracking.py).** Extract frames once per video to a cached JPEG dir (downscaled so max dim ≤ 2048 — SAM2 resizes to 1024² internally anyway; keep the scale factor to map boxes back to source pixels). Init SAM2 video predictor with the user's box at the anchor frame; propagate forward to the end, then (if anchor > 0) backward to the start; merge. Per frame, take the mask's bounding box and centroid. **Loss detection:** mask empty or area < 20% of its rolling median → mark `lost`. Lost segments remain explicit in the track, and the crop planner interpolates or coasts through gaps. Identity switches without lost frames require the planned multi-anchor splicing workflow.

**Crop planning (crop_planner.py — pure NumPy, fully unit-testable).**
1. Input: per-frame centers (with gaps), source dims, output dims, zoom.
2. Fill gaps by linear interpolation between known neighbors; hold last position at ends.
3. Crop window size: aspect = outW/outH; base window = output dims scaled so it fits the source (for 4096×1024 + 1920×1080 request → window 1820×1024), divided by `zoom` (default 1.0, range 1–4), clamped to source.
4. Smooth the center trajectory: dead-zone (ignore moves < `deadZonePx`, default 30) → centered moving average over `windowSec` (default 0.8 s) → per-frame velocity clamp (`maxVelPxPerFrame`, default 28) for pan-like motion.
5. Clamp window fully inside the frame; emit integer, even-valued `{x, y, w, h}` per frame.

**Export (exporter.py).** PyAV: decode source at full resolution, per-frame crop from the plan, high-quality resize (Lanczos via OpenCV) to outW×outH, encode `libx264` (yuv420p, crf 18, source fps), copy/re-encode source audio (aac) with original timing. Progress callback per frame → job WS.

### Device/config matrix (config.py)

| Device | SAM 2.1 | Notes |
|---|---|---|
| CUDA, Turing (2080 Ti) | base-plus, fp16, SDPA | target configuration; peak VRAM and speed need hardware verification |
| CUDA, Ampere+ | large, bf16, SDPA | faster path for newer cards |
| MPS (Mac dev) | base-plus, fp32/fp16 | CPU offload protects long videos |
| CPU | small | works, slow — CI/tests |

## Roadmap (milestones for Codex — each independently verifiable)

**M0 — Scaffold & video I/O.** Move `example` → `examples/example.mp4` (git mv/add). Create backend (uv + FastAPI) and frontend (Vite + React + TS). Implement `POST /api/videos` (+ffprobe metadata), Range-request file serving, frame extraction cache. UI: open the example video, play/pause/scrub, canvas overlay that logs click positions in **source pixel coords** (test with the 4096×1024 pano — the coord mapping must account for letterboxing/object-fit). ✅ Verify: `curl` the API; open UI, scrub video, click prints correct coords.

**M1 — Click-to-select (SAM 2 image).** `sam2_engine.py` with device autodetect; `fetch_models.py` for checkpoints; `POST /api/select/click` returns mask+box; UI shows the mask overlay and a "Track this player" button. ✅ Verify on Mac (MPS): click a player in example.mp4 frame 0 → sensible mask.

**M2 — Video tracking.** SAM2 video propagation job with WS progress + streaming partial results; forward/backward merge; loss detection; `TrackOverlay` draws the live box while scrubbing. ✅ Verify: track a player through the full 930 frames; overlay follows them; job survives target-lost segments.

**M3 — Crop plan + export.** `crop_planner.py` (with pytest unit tests: gap fill, clamping, smoothing determinism, even dims); `exporter.py`; `ExportPanel` with presets 1920×1080 / 1280×720 / custom + zoom + smoothing controls; download link. ✅ Verify: export 1280×720 from example.mp4 → output has correct dims, follows the player smoothly, keeps audio, no edge jitter (`ffprobe` + eyeball).

**M4 — CUDA/Windows readiness.** Tune SAM 2 device selection for Turing and Ampere+, keep the high-resolution click-selection path device-independent, and exercise the full selection→tracking→export pipeline on Windows. ⚠ Verification remains: on the 2080 Ti, confirm click selection produces a sensible mask, tracking completes without OOM, and `nvidia-smi` records SAM 2 peak VRAM and tracking speed.

**M5 — Windows packaging & docs.** `dev.ps1` / `run.ps1` one-command launcher (starts backend serving built frontend, opens browser); README covering Windows install (Python 3.11/3.12, CUDA torch wheel `cu121`+, model download, no compiler needed — SAM2 without its optional CUDA extension), Mac dev setup, and the requirement to supply authorized footage. Optional stretch: PyInstaller one-folder build.

## Risks & mitigations

- **11 GB VRAM pressure** → fp16, base-plus SAM2, and a frame cache ≤ 2048 px. If propagation OOMs, use sam2 `offload_video_to_cpu=True` / `offload_state_to_cpu=True`.
- **SAM 2 on native Windows is hardware-unverified** → record peak VRAM and throughput on the RTX 2080 Ti; if the native environment fails, document WSL2 as a fallback while keeping the UI unchanged.
- **SAM2 drift/ID-switch in crowded scenes** → the UI lets the user re-click at a later frame and the planned multi-anchor workflow will splice the corrected segment into the saved track.
- **930-frame propagation time on MPS** → acceptable for dev (minutes); streaming partial results keep the UI responsive.

## Verification (end-to-end)

1. `scripts/dev.sh` on the Mac → open UI → load `examples/example.mp4` → click a player → track → export 1280×720 → play the result: crop follows the player, audio intact.
2. `pytest backend/tests` green (crop planner math, API contract).
3. On Windows/2080 Ti: run the same click→track→export flow, record CUDA tracking speed and peak SAM 2 VRAM with `nvidia-smi`, and verify both PowerShell launchers.
