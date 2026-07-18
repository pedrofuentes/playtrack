<p align="center">
  <img src="frontend/public/brand/playtrack-lockup.svg" width="360" alt="PlayTrack">
</p>

<p align="center">
  A local virtual camera for panoramic sports footage.<br>
  Select a player, track them with SAM 2, and export a smooth H.264 crop.
</p>

<p align="center">
  <a href="https://pf.run/playtrack/">Website</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="https://github.com/pedrofuentes/playtrack/issues">Issues</a> ·
  <a href="CONTRIBUTING.md">Contributing</a>
</p>

## What PlayTrack does

PlayTrack turns a fixed panoramic recording into a conventional video that follows
one player. Click a player on a clear frame—or describe them on a CUDA machine—then
let SAM 2 propagate the selection through a chosen range. Review track health, tune
the crop dimensions, zoom, and camera smoothness, and export an H.264 MP4 with audio.

The application is single-user and local-first. Videos, frame caches, tracks, and
exports stay on the computer running FastAPI. The installable PWA caches only the
compiled UI and brand assets; video processing still requires the local backend.

Windows with NVIDIA CUDA is the primary target. macOS/Apple Silicon supports click
selection and tracking through MPS. Optional LocateAnything text grounding is
CUDA-only and its weights are non-commercial under NVIDIA's research license.

## Quick start

### Windows + NVIDIA CUDA

Requirements:

- Windows 10 or newer with a current NVIDIA driver.
- [uv](https://docs.astral.sh/uv/getting-started/installation/), Git, and Node.js 20+.
- `ffmpeg` and `ffprobe` on `PATH`.

From PowerShell in the repository root:

```powershell
uv python install 3.12
uv sync --project backend --python 3.12 --extra dev --extra locate

uv pip install --python backend\.venv\Scripts\python.exe --reinstall `
  torch==2.5.1 torchvision==0.20.1 `
  --index-url https://download.pytorch.org/whl/cu121

backend\.venv\Scripts\python.exe scripts\fetch_models.py
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1
```

`run.ps1` checks the toolchain, installs/builds the frontend when needed, starts
PlayTrack at <http://127.0.0.1:8000>, waits for health, and opens the browser.
The first text-selection request downloads roughly 7.7 GB of LocateAnything weights.

For development with FastAPI reload and Vite hot reload:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1
```

### macOS + Apple Silicon

Install uv, Node.js 20+, Git, and FFmpeg, then run:

```bash
uv python install 3.12
uv sync --project backend --python 3.12 --extra dev
npm ci --prefix frontend
backend/.venv/bin/python scripts/fetch_models.py
./scripts/dev.sh
```

Open <http://127.0.0.1:5173>. LocateAnything is intentionally omitted: the text
selection UI is hidden and `POST /api/select/text` returns 501 on non-CUDA hosts.

## Use PlayTrack

1. Open a constant-frame-rate sports video by upload or server path. If
   `examples/example.mp4` exists, PlayTrack opens it automatically. No footage ships
   with the repository; `examples/*.mp4` is gitignored.
2. Mark a useful in/out range, scrub to a clear frame, and click the player. On CUDA,
   you can instead enter a description and confirm one of the candidate boxes.
3. Name the player and start tracking. The overlay fills as SAM 2 propagates forward
   and backward from the anchor.
4. Review coverage and lost-frame ranges. Choose **Set framing** when the track is ready.
5. Select 1080p, 720p, or custom even dimensions; adjust zoom and camera smoothness;
   preview the crop window; then export and download the MP4.

The library persists sources, named player tracks, jobs, and exports across restarts.
Registered source files are never deleted by PlayTrack. Uploaded copies are deleted
only through the library and only from `data/uploads/`.

## Install the PWA

Build the frontend and run the single-process backend:

```bash
cd frontend && npm run build
cd ../backend && uv run uvicorn app.main:app --port 8000
```

Open <http://127.0.0.1:8000> in a PWA-capable browser and use its install action.
The installed shell updates automatically. If FastAPI is stopped, the cached shell
explains how to restart the server and provides a retry action. The service worker
does not runtime-cache `/api`, `/ws`, source videos, exports, or tracking data.

## Configuration

Defaults live in `backend/app/config.py`.

| Variable | Default | Purpose |
|---|---:|---|
| `PLAYTRACK_HOST` | `127.0.0.1` | Launcher bind host; `0.0.0.0` exposes PlayTrack on the LAN without authentication. |
| `PLAYTRACK_ALLOWED_HOSTS` | empty | Comma-separated extra Host header names. |
| `PLAYTRACK_DATA_DIR` | `<repo>/data` | Uploads, frame caches, and SQLite library. |
| `PLAYTRACK_CHECKPOINTS_DIR` | `<repo>/checkpoints` | SAM 2 checkpoint directory. |
| `PLAYTRACK_SAM2_CHECKPOINT` | base-plus checkpoint | Checkpoint override. |
| `PLAYTRACK_SAM2_CONFIG` | base-plus config | SAM 2 model config override. |
| `PLAYTRACK_SAM2_CROP_SIZE` | `1024` | High-resolution click-selection crop in source pixels. |
| `PLAYTRACK_LOCATE_MODEL` | `nvidia/LocateAnything-3B` | Optional text-grounding model ID. |
| `PLAYTRACK_LOCATE_REVISION` | pinned commit | Trusted model-code/weight revision. |
| `PLAYTRACK_FFMPEG` / `PLAYTRACK_FFPROBE` | `ffmpeg` / `ffprobe` | Video tool binaries. |
| `PLAYTRACK_MAX_UPLOAD_BYTES` | `21474836480` | Streaming upload limit (20 GiB). |
| `PLAYTRACK_MAX_EXPORT_WIDTH` / `PLAYTRACK_MAX_EXPORT_HEIGHT` | `4096` / `2160` | Output dimension bounds. |
| `PLAYTRACK_MAX_EXPORT_PIXELS` | `8847360` | Output pixels per frame. |
| `TRACKING_MAX_DIM` | `2048` | Maximum tracking-cache frame dimension. |
| `SAM2_OFFLOAD_VIDEO_TO_CPU` / `SAM2_OFFLOAD_STATE_TO_CPU` | `0` | SAM 2 memory offload; forced on MPS. |
| `LOCATE_MAX_INPUT_DIM` | `2500` | Text-grounding downscale bound. |
| `LOCATE_RESCUE_ENABLED` / `LOCATE_RESCUE_AFTER` / `LOCATE_RESCUE_MIN_SCORE` | `1` / `15` / `0.5` | Occlusion-rescue controls. |

This release is a clean environment-variable rename: obsolete `FINDME_*` settings are
not accepted. Unbranded `SAM2_*`, `LOCATE_*`, and `TRACKING_MAX_DIM` settings remain.

### Library migration

The canonical library is `data/library/playtrack.sqlite3` with WAL journaling and full
synchronous writes. On first startup, when only `findme.sqlite3` exists, PlayTrack:

1. copies it with SQLite's backup API (including committed WAL records),
2. validates the copy with `PRAGMA integrity_check`, and
3. atomically installs `playtrack.sqlite3`.

The legacy database and sidecars are retained as recovery backups. Later starts always
prefer the canonical database. Legacy JSON catalogs remain intentionally ignored.

## Architecture

```text
frontend/   React + Vite + TypeScript editor + generateSW PWA
backend/    FastAPI + SAM 2 + LocateAnything + PyAV/OpenCV
website/    Dependency-free static product site for GitHub Pages
scripts/    macOS/Windows launchers and model fetcher
```

HTTP routes, payloads, WebSocket protocols, smoothing compatibility keys, and runtime
directory boundaries are documented for coding agents in [AGENTS.md](AGENTS.md).
The original M0–M5 architecture roadmap is in [docs/plan.md](docs/plan.md); dated
FindMe specs under `docs/superpowers/` are historical records from before the rename.

## Known limitations

- Full 930-frame tracking takes about 20 minutes on Apple Silicon. Use short ranges to iterate.
- SAM 2 can switch identity when players overlap without producing lost frames. Re-anchor
  after the collision; multi-anchor splicing is the planned fix.
- LocateAnything visual-prompt rescue remains dormant because compatible public weights
  are not available. Text grounding works independently on CUDA.
- Tracking/export each have one worker and two queue slots. Overload returns retryable HTTP 429.
- Variable-frame-rate sources are rejected so frame-indexed tracking and export cannot drift.
- RTX 2080 Ti support exists in code but the real 11 GB VRAM ceiling and speed remain unverified.
- PlayTrack has no authentication. Do not expose it to the public internet.

## Contributing and security

PlayTrack source code is available under the [MIT License](LICENSE). Third-party
dependencies and model weights keep their upstream licenses.

- [Contributing guide](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Report a bug](https://github.com/pedrofuentes/playtrack/issues/new?template=bug_report.yml)
- [Request a feature](https://github.com/pedrofuentes/playtrack/issues/new?template=feature_request.yml)

## Verification

```bash
cd backend && uv run --extra dev pytest -m "not integration"
cd ../frontend && npm test && npm run typecheck && npm run build
npm run test:pwa
cd .. && node website/test-site.mjs
```

Behavior changes should also exercise register → select → track → crop plan → export
against an authorized real clip, inspect the MP4 with `ffprobe`, and visually review
editor overlays and exported frames.
