<p align="center">
  <img src="website/assets/playtrack-bright.png" width="360" alt="PlayTrack — Follow Every Move">
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
one player. Click a player on a clear frame, then let SAM 2 propagate the selection
through a chosen range. Review track health, tune
the crop dimensions, zoom, and camera smoothness, and export an H.264 MP4 with audio.

The application is single-user and local-first. Videos, frame caches, tracks, and
exports stay on the computer running FastAPI. The installable PWA caches only the
compiled UI and brand assets; video processing still requires the local backend.

Windows with NVIDIA CUDA is the primary target. macOS/Apple Silicon supports click
selection and tracking through MPS.

## Quick start

### Windows + NVIDIA CUDA

Requirements:

- Windows 10 or newer with a current NVIDIA driver.
- [uv](https://docs.astral.sh/uv/getting-started/installation/), Git, and Node.js 20+.

From PowerShell in the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1
```

The explicit `powershell -ExecutionPolicy Bypass -File` form works when unsigned
local scripts would otherwise be blocked. `Bypass` applies only to the newly launched
PowerShell process and does not change your saved execution policy. A policy enforced
through Group Policy can still take precedence. If your current PowerShell session
already permits local scripts, these shorter forms are equivalent:

```powershell
.\scripts\setup.ps1
.\scripts\run.ps1
.\scripts\dev.ps1
```

`setup.ps1` installs Python 3.12, synchronizes the backend, installs frontend
dependencies, fetches the SAM 2 checkpoint, and installs a pinned portable FFmpeg
build under the gitignored `.tools/ffmpeg` directory. It does not require administrator
rights or modify the system `PATH`.

`run.ps1` checks the toolchain and video tools, installs/builds the frontend when
needed, starts PlayTrack at <http://127.0.0.1:8000>, waits for health, and opens the browser.
On Windows, uv installs CUDA (cu124) PyTorch wheels automatically; no manual torch install is needed.

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

Open <http://127.0.0.1:5173> on the PlayTrack computer.

To use the development UI from another device on the same trusted local network:

```bash
./scripts/dev.sh --network
```

This binds FastAPI to `0.0.0.0:8000` and Vite to `0.0.0.0:5173`. Open the
network URL printed by the launcher. Network mode has no authentication; never expose
these ports to the internet or an untrusted network.

## Use PlayTrack

1. Open a constant-frame-rate sports video by upload or server path. If
   `examples/example.mp4` exists, PlayTrack opens it automatically. No footage ships
   with the repository; `examples/*.mp4` is gitignored.
2. Mark a useful in/out range, scrub to a clear frame, and click the player.
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
| `PLAYTRACK_HOST` | `127.0.0.1` | Backward-compatible launcher bind override; `scripts/dev.sh --network` is the preferred development interface for explicit `0.0.0.0` LAN binding without authentication. |
| `PLAYTRACK_ALLOWED_HOSTS` | empty | Comma-separated extra Host header names. |
| `PLAYTRACK_DATA_DIR` | `<repo>/data` | Uploads, frame caches, and SQLite library. |
| `PLAYTRACK_CHECKPOINTS_DIR` | `<repo>/checkpoints` | SAM 2 checkpoint directory. |
| `PLAYTRACK_SAM2_CHECKPOINT` | base-plus checkpoint | Checkpoint override. |
| `PLAYTRACK_SAM2_CONFIG` | base-plus config | SAM 2 model config override. |
| `PLAYTRACK_SAM2_CROP_SIZE` | `1024` | High-resolution click-selection crop in source pixels. |
| `PLAYTRACK_FFMPEG` / `PLAYTRACK_FFPROBE` | `ffmpeg` / `ffprobe` | Video tool binaries. Windows launchers resolve explicit overrides first, then `PATH`, then `.tools/ffmpeg`. |
| `PLAYTRACK_MAX_UPLOAD_BYTES` | `21474836480` | Streaming upload limit (20 GiB). |
| `PLAYTRACK_MAX_EXPORT_WIDTH` / `PLAYTRACK_MAX_EXPORT_HEIGHT` | `4096` / `2160` | Output dimension bounds. |
| `PLAYTRACK_MAX_EXPORT_PIXELS` | `8847360` | Output pixels per frame. |
| `TRACKING_MAX_DIM` | `2048` | Maximum tracking-cache frame dimension. |
| `SAM2_OFFLOAD_VIDEO_TO_CPU` / `SAM2_OFFLOAD_STATE_TO_CPU` | `0` | SAM 2 memory offload; forced on MPS, auto-enabled on CUDA when the video tensor cannot fit free VRAM. |

This release is a clean environment-variable rename: obsolete `FINDME_*` settings are
not accepted. Unbranded `SAM2_*` and `TRACKING_MAX_DIM` settings remain.

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
backend/    FastAPI + SAM 2 + PyAV/OpenCV
website/    Dependency-free static product site for GitHub Pages
scripts/    macOS/Windows setup, launchers, and model fetcher
```

HTTP routes, payloads, WebSocket protocols, smoothing compatibility keys, and runtime
directory boundaries are documented for coding agents in [AGENTS.md](AGENTS.md).
The original M0–M5 architecture roadmap is in [docs/plan.md](docs/plan.md); dated
FindMe specs under `docs/superpowers/` are historical records from before the rename.

## Known limitations

- Full 930-frame tracking takes about 20 minutes on Apple Silicon and about 3 minutes on an RTX 2080 Ti. Use short ranges to iterate.
- SAM 2 can switch identity when players overlap without producing lost frames. Re-anchor
  after the collision; multi-anchor splicing is the planned fix.
- Tracking/export each have one worker and two queue slots. Overload returns retryable HTTP 429.
- Variable-frame-rate sources are rejected so frame-indexed tracking and export cannot drift.
- Verified on RTX 2080 Ti (2026-08-28): 930-frame track in about 3 minutes (~4.8 fps) at ~4.3 GB peak VRAM with automatic CPU offload.
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
