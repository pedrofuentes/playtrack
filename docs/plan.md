# FindMe — Player-Tracking Virtual Camera App

## Context

Pedro wants a Windows app where you open a sports video, select a player (by clicking on them or describing them in text), the app tracks that player across the video, and exports a cropped video that follows the player at user-chosen output dimensions. The test asset is a **4096×1024, 30 fps, 31 s (930 frames) panoramic match video** — the classic "virtual camera over a panorama" use case (Veo/Pixellot style).

This document is the roadmap + implementation spec **to be executed by Codex**. The test video lives at `examples/example.mp4`.

### Key research findings that shaped the design

- **LocateAnything** (`nvidia/LocateAnything-3B`, code in `NVlabs/Eagle/Embodied`) is a **single-image** vision-language grounding model — open-vocab detection from **text prompts** and **visual prompts** (an image crop of the target). It has **no video/tracking mode**. ~7.7 GB weights, CUDA-only, ~1–2 s/frame, weights licensed **non-commercial**. Loaded via `AutoModel.from_pretrained("nvidia/LocateAnything-3B", trust_remote_code=True)`; repo provides `LocateAnythingWorker` with `detect`, `ground_text`, `detect_visual_prompt`, and `parse_boxes` helpers.
- **SAM 2.1** (Meta, Apache 2.0) is a promptable **video** segmentation model: click/box on one frame → mask propagated across all frames (streaming memory attention). Runs on CUDA, MPS, and CPU.
- **Decision (confirmed with Pedro): hybrid pipeline.** LocateAnything handles *finding* the player (text-prompt selection, occlusion/loss recovery via visual prompt); SAM 2 handles *frame-to-frame tracking*. Click-to-select goes straight to SAM 2.
- **Target hardware: Windows + RTX 2080 Ti (Turing, 11 GB).** Constraints: no native bf16 → run LocateAnything in **fp16**; no FlashAttention-2 on Turing → force **SDPA** attention; 11 GB is too small for both models resident → **load LocateAnything on demand and free VRAM before SAM 2 propagation**; default SAM 2.1 **base-plus** checkpoint.
- **Dev machine is a Mac** → everything except LocateAnything must run on MPS/CPU. LocateAnything is feature-flagged: enabled on CUDA, disabled (text-prompt UI hidden, API returns 501) elsewhere.

## Architecture

```
┌────────────────────────────┐        HTTP + WebSocket        ┌─────────────────────────────┐
│ frontend/  (TypeScript)    │ ─────────────────────────────► │ backend/  (Python 3.11/3.12)│
│ React + Vite               │                                │ FastAPI + uvicorn           │
│ - <video> player + canvas  │   /api/videos, /api/select,    │ - VideoStore (probe/frames) │
│   overlay (click, boxes,   │   /api/track, /api/export,     │ - Selector: SAM2 image      │
│   track path, crop preview)│   /ws/jobs/{id}                │   predictor + LocateAnything│
│ - text-prompt select       │                                │ - Tracker: SAM2 video       │
│ - export dims / zoom /     │                                │   propagation (+ LA rescue) │
│   smoothing controls       │                                │ - CropPlanner: smoothing    │
└────────────────────────────┘                                │ - Exporter: PyAV crop+encode│
                                                              └─────────────────────────────┘
```

Single-user localhost app. One command starts the backend, which serves the built frontend; dev mode runs Vite separately with a proxy.

### Repo layout

```
FindMe/
├── docs/plan.md                  # this spec (committed for Codex)
├── examples/example.mp4          # moved from repo-root `example`
├── backend/
│   ├── pyproject.toml            # uv-managed; torch, sam2, transformers, fastapi, av, opencv-python-headless, pillow, numpy, websockets
│   ├── app/
│   │   ├── main.py               # FastAPI app, static serving, CORS (dev)
│   │   ├── config.py             # device autodetect (cuda→fp16/sdpa on Turing, bf16 on Ampere+; mps; cpu), model paths, feature flags
│   │   ├── videos.py             # register/upload, ffprobe metadata, frame extraction cache, poster frames
│   │   ├── selection.py          # click→SAM2 image mask; text→LocateAnything ground_text→box
│   │   ├── tracking.py           # SAM2 video propagation job; per-frame box/centroid; loss detection + LA visual-prompt rescue
│   │   ├── crop_planner.py       # trajectory smoothing + crop-window path (pure functions, no torch)
│   │   ├── exporter.py           # PyAV: decode→crop→resize→encode h264 + copy source audio
│   │   ├── jobs.py               # in-memory job registry, progress via WebSocket
│   │   └── models/
│   │       ├── sam2_engine.py    # lazy singleton: image predictor + video predictor, device/dtype handling
│   │       └── locate_engine.py  # lazy load/unload LocateAnything (fp16+sdpa), text + visual prompt detect; absent→disabled
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
│   └── fetch_models.py           # download SAM2.1 checkpoints (+ LocateAnything on CUDA machines)
└── README.md                     # setup for Mac (dev) and Windows/2080 Ti (full)
```

### API surface

- `POST /api/videos` — body `{path}` (local file, e.g. examples/example.mp4) or multipart upload → `{videoId, width, height, fps, nbFrames, duration}`; video then served at `GET /api/videos/{id}/file` with Range support so the browser `<video>` plays it natively.
- `POST /api/select/click` — `{videoId, frameIdx, x, y}` (source pixels) → SAM2 image predictor on that frame → `{box, maskPng (base64), score}` for instant visual confirmation.
- `POST /api/select/text` — `{videoId, frameIdx, prompt}` → LocateAnything `ground_text` → `{candidates: [{box, score}]}`; 501 + reason when LocateAnything unavailable (non-CUDA).
- `POST /api/track` — `{videoId, frameIdx, box}` → starts job → `{jobId}`. Result: `{track: [{frameIdx, box|null, center|null, lost}]}` (null while target absent).
- `POST /api/export` — `{videoId, jobId(track), outWidth, outHeight, zoom, smoothing:{windowSec, deadZonePx, maxVelPxPerFrame}}` → export job → `{jobId}`; done → `GET /api/exports/{id}.mp4`.
- `WS /ws/jobs/{jobId}` — `{state, progress: 0..1, message}` stream; also used to stream partial track results so the overlay fills in live.

### Core algorithms

**Tracking (tracking.py).** Extract frames once per video to a cached JPEG dir (downscaled so max dim ≤ 2048 — SAM2 resizes to 1024² internally anyway; keep the scale factor to map boxes back to source pixels). Init SAM2 video predictor with the user's box at the anchor frame; propagate forward to the end, then (if anchor > 0) backward to the start; merge. Per frame, take the mask's bounding box and centroid. **Loss detection:** mask empty or area < 20% of its rolling median → mark `lost`. **Rescue (CUDA only):** on ≥ `rescue_after` (default 15) consecutive lost frames, run LocateAnything `detect_visual_prompt` using a saved crop of the player from the anchor frame; if a confident match is found, re-seed a fresh SAM2 propagation from that frame. Free LocateAnything VRAM (`del` + `torch.cuda.empty_cache()`) before resuming SAM2. Without CUDA, lost segments just stay lost and the crop planner coasts through them.

**Crop planning (crop_planner.py — pure NumPy, fully unit-testable).**
1. Input: per-frame centers (with gaps), source dims, output dims, zoom.
2. Fill gaps by linear interpolation between known neighbors; hold last position at ends.
3. Crop window size: aspect = outW/outH; base window = output dims scaled so it fits the source (for 4096×1024 + 1920×1080 request → window 1820×1024), divided by `zoom` (default 1.0, range 1–4), clamped to source.
4. Smooth the center trajectory: dead-zone (ignore moves < `deadZonePx`, default 30) → centered moving average over `windowSec` (default 0.8 s) → per-frame velocity clamp (`maxVelPxPerFrame`, default 28) for pan-like motion.
5. Clamp window fully inside the frame; emit integer, even-valued `{x, y, w, h}` per frame.

**Export (exporter.py).** PyAV: decode source at full resolution, per-frame crop from the plan, high-quality resize (Lanczos via OpenCV) to outW×outH, encode `libx264` (yuv420p, crf 18, source fps), copy/re-encode source audio (aac) with original timing. Progress callback per frame → job WS.

### Device/config matrix (config.py)

| Device | SAM 2.1 | LocateAnything | Notes |
|---|---|---|---|
| CUDA, Turing (2080 Ti) | base-plus, fp16 | fp16 + `attn_implementation="sdpa"`, on-demand load/unload | never both resident during propagation |
| CUDA, Ampere+ | large, bf16 | bf16, sdpa (flash-attn optional) | |
| MPS (Mac dev) | base-plus, fp32/fp16 | disabled | text-select hidden in UI |
| CPU | small | disabled | works, slow — CI/tests |

## Roadmap (milestones for Codex — each independently verifiable)

**M0 — Scaffold & video I/O.** Move `example` → `examples/example.mp4` (git mv/add). Create backend (uv + FastAPI) and frontend (Vite + React + TS). Implement `POST /api/videos` (+ffprobe metadata), Range-request file serving, frame extraction cache. UI: open the example video, play/pause/scrub, canvas overlay that logs click positions in **source pixel coords** (test with the 4096×1024 pano — the coord mapping must account for letterboxing/object-fit). ✅ Verify: `curl` the API; open UI, scrub video, click prints correct coords.

**M1 — Click-to-select (SAM 2 image).** `sam2_engine.py` with device autodetect; `fetch_models.py` for checkpoints; `POST /api/select/click` returns mask+box; UI shows the mask overlay and a "Track this player" button. ✅ Verify on Mac (MPS): click a player in example.mp4 frame 0 → sensible mask.

**M2 — Video tracking.** SAM2 video propagation job with WS progress + streaming partial results; forward/backward merge; loss detection; `TrackOverlay` draws the live box while scrubbing. ✅ Verify: track a player through the full 930 frames; overlay follows them; job survives target-lost segments.

**M3 — Crop plan + export.** `crop_planner.py` (with pytest unit tests: gap fill, clamping, smoothing determinism, even dims); `exporter.py`; `ExportPanel` with presets 1920×1080 / 1280×720 / custom + zoom + smoothing controls; download link. ✅ Verify: export 1280×720 from example.mp4 → output has correct dims, follows the player smoothly, keeps audio, no edge jitter (`ffprobe` + eyeball).

**M4 — LocateAnything integration (CUDA/Windows).** `locate_engine.py` (fp16, sdpa, lazy load/unload, `trust_remote_code`); `POST /api/select/text` with candidate boxes UI (user confirms one → same tracking flow); occlusion rescue in tracking.py; feature-flag plumbing so non-CUDA hosts degrade cleanly. ✅ Verify on the 2080 Ti: text prompt like "the player in the white jersey" returns a box; VRAM stays under 11 GB across select→track→export (`nvidia-smi` while running); rescue path re-acquires after a simulated occlusion (start track just before the player is obscured).

**M5 — Windows packaging & docs.** `dev.ps1` / `run.ps1` one-command launcher (starts backend serving built frontend, opens browser); README covering: Windows install (Python 3.11/3.12, CUDA torch wheel `cu121`+, model download, no compiler needed — SAM2 without its optional CUDA extension), Mac dev setup, LocateAnything license note (**non-commercial weights** — app is for personal use). Optional stretch: PyInstaller one-folder build.

## Risks & mitigations

- **11 GB VRAM pressure** → sequential model residency, fp16, base-plus SAM2, frame cache ≤ 2048 px. If propagation OOMs, sam2 `offload_video_to_cpu=True` / `offload_state_to_cpu=True`.
- **LocateAnything on native Windows is untested by NVIDIA** → we only need `transformers` inference (no deepspeed/flash-attn/liger from their training stack); pin `transformers==4.57.1` to match the remote code. If it still fails on Windows, fallback documented: run backend under WSL2 (UI unchanged).
- **SAM2 drift/ID-switch in crowded scenes** → backward+forward propagation from the anchor, LA rescue, and the UI lets the user re-click at any frame to re-anchor (re-run track from there, splice paths).
- **930-frame propagation time on MPS** → acceptable for dev (minutes); streaming partial results keep the UI responsive.

## Verification (end-to-end)

1. `scripts/dev.sh` on the Mac → open UI → load `examples/example.mp4` → click a player → track → export 1280×720 → play the result: crop follows the player, audio intact.
2. `pytest backend/tests` green (crop planner math, API contract).
3. On Windows/2080 Ti: same flow plus text-prompt selection and occlusion rescue; `nvidia-smi` peak < 11 GB.
