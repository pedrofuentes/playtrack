# FindMe — Agent Guide

Read this first. It is the canonical agent-facing doc; `CLAUDE.md` just imports it.
Human docs: `README.md` (setup + user guide), `docs/plan.md` (original spec, M0–M5 roadmap).

## What this is

A local web app that turns panoramic sports footage into a "virtual camera": the user
opens a video, selects a player (click, or text prompt on CUDA), SAM 2 tracks them
through the video, and the app exports a cropped video that smoothly follows the player
at user-chosen dimensions. Single user, localhost by default.

Test asset: `examples/example.mp4` — 4096×1024 panoramic hockey video, 30 fps, 930
frames. Players are only ~60 px tall in it; several design decisions below follow from
that. The file is **not committed** (third-party footage; `examples/*.mp4` is
gitignored) — supply your own panoramic clip at that path for end-to-end verification.

## Architecture

```
frontend/  React + Vite + TypeScript SPA
  src/App.tsx                 app state machine (open → select → track → export)
  src/api.ts                  typed client + WebSocket job watcher
  src/geometry.ts             pure letterbox/zoom coordinate math (unit-tested)
  src/components/
    OpenVideoPanel.tsx        upload (multipart) or open-by-server-path
    VideoStage.tsx            <video> + overlay canvases; wheel zoom / drag pan
    TrackOverlay.tsx          tracked box synced to currentTime
    CropOverlay.tsx           planned crop-window rectangle preview
    ExportPanel.tsx           dimensions, camera-smoothness slider, export job
    LibraryPanel.tsx          persisted videos/tracks/exports; delete; re-export

backend/   FastAPI (Python 3.12, uv-managed)
  app/main.py                 routes, WS /ws/jobs/{id}, serves frontend/dist + SPA fallback
  app/config.py               Settings + env vars (single source of truth for config)
  app/videos.py               VideoStore: register/upload, ffprobe metadata, frame caches
  app/selection.py            click→SAM2 image predict on a high-res crop; text→LocateAnything
  app/tracking.py             SAM2 video propagation job, loss detection, LocateAnything rescue
  app/crop_planner.py         pure NumPy: gap fill, spring smoothing, subpixel crop windows
  app/exporter.py             PyAV decode → cv2.getRectSubPix crop → Lanczos resize → h264+audio
  app/jobs.py                 in-memory job registry (rehydrated from library on startup)
  app/library.py              SQLite persistence: data/library/findme.sqlite3 (WAL + FULL sync)
  app/models/sam2_engine.py   lazy SAM2 image/video engines, device autodetect
  app/models/locate_engine.py LocateAnything-3B (CUDA only), lazy load/unload

scripts/   dev.sh (Mac dev), dev.ps1 + run.ps1 (Windows), fetch_models.py (SAM2 checkpoints)
```

Runtime dirs (gitignored, never commit): `data/` (uploads, frame caches, library SQLite),
`exports/`, `checkpoints/`.

## Commands

```bash
# Backend
cd backend
uv sync --extra dev                                  # deps (torch, sam2 from git, fastapi…)
uv run --extra dev pytest -m "not integration"       # weight-free suite — the default gate
python3 ../scripts/fetch_models.py                   # SAM2.1 base-plus → checkpoints/ (~309MB)
uv run --extra dev pytest                             # full suite (needs checkpoint; CUDA tests skip off-CUDA)
uv sync --extra dev --extra locate                    # adds transformers for LocateAnything (CUDA machines)

# Frontend
cd frontend
npm install && npm test && npm run build              # vitest + production bundle

# Run the app
scripts/dev.sh          # Mac dev: uvicorn --reload :8000 + Vite :5173
scripts/run.ps1         # Windows: single process serving frontend/dist on :8000
# manual equivalent: cd backend && uv run uvicorn app.main:app --port 8000
```

The backend serves `frontend/dist` when it exists — rebuild the frontend for UI changes
to reach the running app; there is no hot reload in production mode.

## Configuration (env vars, defaults in `backend/app/config.py`)

| Var | Default | Meaning |
|---|---|---|
| `FINDME_HOST` | `127.0.0.1` | bind host in dev.sh/run.ps1; `0.0.0.0` exposes on LAN (origin/host checks, but no authentication) |
| `FINDME_ALLOWED_HOSTS` | empty | comma-separated extra Host header names accepted by the API boundary |
| `FINDME_MAX_UPLOAD_BYTES` | `21474836480` (20 GiB) | maximum multipart video upload size, enforced while streaming |
| `FINDME_DATA_DIR` | `<repo>/data` | uploads, frame caches, library persistence |
| `FINDME_CHECKPOINTS_DIR` | `<repo>/checkpoints` | SAM2 weights dir |
| `FINDME_SAM2_CHECKPOINT` / `FINDME_SAM2_CONFIG` | base-plus | checkpoint/config override |
| `FINDME_SAM2_CROP_SIZE` | `1024` | click-select high-res crop size (source px) |
| `SAM2_OFFLOAD_VIDEO_TO_CPU` / `SAM2_OFFLOAD_STATE_TO_CPU` | `0` | forced on automatically on MPS |
| `TRACKING_MAX_DIM` | `2048` | tracking frame-cache resolution (4096 ≈ 2× slower, no accuracy gain — measured) |
| `FINDME_LOCATE_MODEL` | `nvidia/LocateAnything-3B` | HF model id |
| `FINDME_LOCATE_REVISION` | pinned commit | exact trusted model-code/weight revision passed to Transformers |
| `LOCATE_MAX_INPUT_DIM` | `2500` | downscale bound for text grounding |
| `LOCATE_RESCUE_ENABLED` / `LOCATE_RESCUE_AFTER` / `LOCATE_RESCUE_MIN_SCORE` | `1` / `15` / `0.5` | occlusion-rescue tuning |
| `FINDME_FFMPEG` / `FINDME_FFPROBE` | `ffmpeg`/`ffprobe` | binary paths |
| `FINDME_MAX_EXPORT_WIDTH` / `FINDME_MAX_EXPORT_HEIGHT` | `4096` / `2160` | maximum output dimensions |
| `FINDME_MAX_EXPORT_PIXELS` | `8847360` | maximum output pixels per frame |

## Device matrix

| Device | SAM 2.1 | LocateAnything |
|---|---|---|
| CUDA Turing (target: RTX 2080 Ti, 11 GB) | base-plus, fp16, SDPA (flash-attn unsupported) | fp16 + SDPA, lazy load/**unload before SAM2 runs** (VRAM) |
| CUDA Ampere+ | large, bf16 | bf16 + SDPA |
| MPS (Mac dev) | base-plus, offload forced | disabled (API returns 501; UI hides text search) |
| CPU | small | disabled |

`GET /api/features` reports availability; the frontend adapts. LocateAnything weights
are **non-commercial** (NVIDIA research license) — keep this app personal-use.

## Conventions and rules

- Tests marked `integration` may need model weights or CUDA and must skip cleanly when
  absent. Never make the unmarked suite depend on weights, network, or GPUs.
- `frontend/src/geometry.ts` and `crop_planner.py` are pure and unit-tested — extend
  them rather than inlining coordinate/trajectory math elsewhere.
- Deletion of user data happens **only** in the library delete endpoints, and uploaded
  media files are deleted only when they live under `data/uploads/`; never delete files
  the user registered by path.
- A dev uvicorn may be running against this working tree; don't kill it or mutate the
  live `data/` directory as part of unrelated work.
- Keep `uv.lock` in sync (`uv sync --extra dev` after dependency edits). sam2 is a git
  dependency; `[tool.hatch.metadata] allow-direct-references = true` is required.
- Smoothing API accepts legacy keys (`windowSec`→tau; `deadZonePx`/`maxVelPxPerFrame`
  ignored) — preserve that compatibility.
- Library persistence is a clean-break SQLite format. Legacy `videos.json`,
  `exports.json`, and `tracks/*.json` files are intentionally ignored and must not be
  imported implicitly.
- Commits: `M<n>: summary` for milestones, plain imperative subject for fixes.

## Known pitfalls (learned the hard way — don't rediscover)

- **MPS long-video crash**: SAM2's stacked video tensor exceeds MPSGraph's INT_MAX above
  ~750 frames; `sam2_engine.py` force-enables CPU offload on MPS. Don't remove it.
- **Small players**: click-select runs SAM2 on a `FINDME_SAM2_CROP_SIZE` window around
  the click, not the full panorama (a 4096-wide frame resized to SAM2's internal 1024²
  leaves a player ~15 px). Don't "simplify" it to full-frame.
- **Identity switch**: when players physically collide, SAM2 can exit the collision
  following the wrong player, with zero `lost` frames — loss detection cannot catch it,
  and raising `TRACKING_MAX_DIM` to 4096 does not fix it (verified on the example at
  ~frame 650). The real fix is the planned multi-anchor splicing feature.
- **LocateAnything rescue is dormant**: the public 3B checkpoint doesn't support
  visual-prompt inference yet; the rescue path activates only when NVIDIA ships those
  weights. Text grounding works. Candidate scores are uncalibrated (1.0).
- The macOS `av`/`cv2` duplicate-dylib objc warning on export is benign noise.
- Full-video tracking takes ~20 min on Apple Silicon (930 frames) — design UX and tests
  accordingly; CI-scale tests must use short synthetic clips.

## Status and open work

M0–M7 are complete and committed (git log is authoritative). Not yet done:

1. **Windows/RTX 2080 Ti verification** (code exists, hardware untested): `run.ps1` /
   `dev.ps1`, LocateAnything real-model text selection, VRAM ceiling under 11 GB across
   select→track→export, CUDA tracking speed.
2. **Multi-anchor track splicing** (proposed, top priority for contact sports): re-anchor
   the track after an identity switch and merge segments into one exportable track.
3. Track-health summary UI (lost-segment ranges, jump-to-frame).
4. Network-exposure hardening (auth token, restrict path registration) if LAN use
   becomes permanent.
5. PyInstaller one-folder packaging (deferred stretch goal).

## Verification expectations

Before claiming work done: run both suites (backend weight-free + frontend) and
`npm run build`. For behavior changes, exercise the real flow against
`examples/example.mp4` through the HTTP API (register → select → track → export), check
outputs with `ffprobe`, and inspect frames/overlays visually where relevant. Report
what was actually run and observed.
