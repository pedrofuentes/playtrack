# FindMe

FindMe turns panoramic sports footage into a conventional cropped video that
follows one player. Select the player by clicking them, or use a text prompt on
a CUDA machine; SAM 2 tracks the selection, FindMe previews a smoothed crop,
and PyAV exports an H.264 MP4 with audio.

The primary deployment target is Windows with an NVIDIA RTX 2080 Ti. macOS is
supported for development and click-to-select/tracking through MPS;
LocateAnything text selection is CUDA-only.

Working on this repo with a coding agent (Claude Code, Codex, or others)? Start
with [AGENTS.md](AGENTS.md) — architecture map, commands, conventions, and
known pitfalls.

## Windows quick start (RTX 2080 Ti)

Requirements:

- Windows 10 or newer and a current NVIDIA driver.
- [Node.js 20 or newer](https://nodejs.org/en/download) with npm.
- `ffmpeg` and `ffprobe` on `PATH`; start at the
  [official FFmpeg download page](https://ffmpeg.org/download.html).
- Git, to install the official SAM 2 dependency referenced by the backend.

Open PowerShell in the repository root. Install
[uv](https://docs.astral.sh/uv/getting-started/installation/) if necessary,
then restart PowerShell so the updated `PATH` is visible:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Let uv install Python 3.12 and create the backend environment with development
and LocateAnything dependencies:

```powershell
uv python install 3.12
uv sync --project backend --python 3.12 --extra dev --extra locate
```

Replace the generic Torch packages in that environment with the official CUDA
12.1 wheels. PyTorch also publishes newer CUDA indexes; use one supported by
your installed driver if you intentionally move beyond the versions pinned by
this project.

```powershell
uv pip install --python backend\.venv\Scripts\python.exe --reinstall `
  torch==2.5.1 torchvision==0.20.1 `
  --index-url https://download.pytorch.org/whl/cu121
```

Download the default SAM 2.1 base-plus checkpoint, then launch FindMe:

```powershell
backend\.venv\Scripts\python.exe scripts\fetch_models.py
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1
```

`run.ps1` checks uv, Node, and npm; installs frontend packages when necessary;
rebuilds `frontend/dist` only when it is missing or older than its inputs;
starts the backend at <http://127.0.0.1:8000>; waits for its health endpoint;
and opens the default browser. Press Ctrl+C in its PowerShell window to stop
the process tree it started.

The first text-selection request downloads approximately 7.7 GB of
`nvidia/LocateAnything-3B` weights from Hugging Face. SAM 2 works without its
optional compiled CUDA extension, so this setup does not require a Visual
Studio C++ build toolchain.

### Windows development mode

After completing the setup above, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1
```

This starts uvicorn with reload at <http://127.0.0.1:8000> and Vite at
<http://127.0.0.1:5173>, opens the Vite URL, and stops both process trees when
either server exits or the script is interrupted.

## macOS development quick start

Install uv, Node.js 20+, and FFmpeg using your preferred package manager, then
from the repository root run:

```bash
uv python install 3.12
uv sync --project backend --python 3.12 --extra dev
npm ci --prefix frontend
backend/.venv/bin/python scripts/fetch_models.py
./scripts/dev.sh
```

Open <http://127.0.0.1:5173>. SAM 2 uses MPS
when available. LocateAnything is intentionally not installed, its prompt UI
is hidden, and `POST /api/select/text` returns 501 on non-CUDA hosts.

## User guide

1. Put a source video at `examples/example.mp4` before launch (no example clip
   ships with the repo — `examples/*.mp4` is gitignored). The UI opens that path
   automatically when present, and you can also upload a video or open any
   server path from the Open video panel. Sources must use a constant frame rate;
   variable-frame-rate clips are rejected at registration so frame-indexed tracking
   and export cannot silently drift.
2. Scrub to a clear frame. Click the player for a SAM 2 mask. On CUDA, you can
   instead describe the player—for example, “the player in the white jersey”—
   and click one of the pink candidate boxes to confirm it.
3. Choose **Track this player**. The overlay fills in while forward and backward
   SAM 2 propagation runs, and stays synchronized while you play or scrub.
4. When tracking completes, choose 1920×1080, 1280×720, or custom even output
   dimensions. Adjust zoom and smoothing while previewing the crop rectangle.
5. Choose **Export video**, wait for the progress bar, then use the download
   link. Completed MP4 files are also stored in the ignored `exports/` folder.

If the tracker switches to another player, scrub to a later frame where the
correct player is distinct, click that player again, and start a new track from
that anchor.

## Runtime configuration

| Variable | Default | Purpose |
|---|---:|---|
| `TRACKING_MAX_DIM` | `2048` | Maximum dimension of SAM 2 tracking-cache frames. |
| `SAM2_OFFLOAD_VIDEO_TO_CPU` | `false` | Keep decoded tracking frames in system memory. |
| `SAM2_OFFLOAD_STATE_TO_CPU` | `false` | Keep SAM 2 propagation state in system memory. |
| `LOCATE_MAX_INPUT_DIM` | `2500` | Maximum LocateAnything input dimension before rescaling. |
| `LOCATE_RESCUE_ENABLED` | `true` | Enable CUDA occlusion rescue when compatible weights exist. |
| `LOCATE_RESCUE_AFTER` | `15` | Consecutive lost frames before rescue is attempted. |
| `LOCATE_RESCUE_MIN_SCORE` | `0.5` | Minimum rescue-candidate score. |

In PowerShell, set a value for the current session before starting FindMe:

```powershell
$env:TRACKING_MAX_DIM = '4096'
.\scripts\run.ps1
```

## Troubleshooting

### Long videos on Apple MPS

The SAM 2 video wrapper automatically offloads video frames and propagation
state to CPU on MPS, even when the two offload environment variables are not
set. This avoids the tensor-size limit that otherwise appears on longer clips;
tracking will use more system memory and can take several minutes.

### Small players or tracking memory pressure

`TRACKING_MAX_DIM=2048` halves a 4096×1024 panorama before SAM 2 sees it. Raise
the value to `4096` when small players need more detail. Higher values improve
subject resolution but increase frame-cache size, system RAM, GPU/MPS memory,
and propagation time. Lower it if tracking runs out of memory.

### The box switches to another player

SAM 2 can switch identity when players overlap, collide, or wear very similar
uniforms. Find a clean frame after the collision, click the intended player,
and run **Track this player** again to re-anchor. FindMe does not yet splice a
manual correction into an existing completed track.

### LocateAnything is hidden or returns 501

LocateAnything is disabled without NVIDIA CUDA or when the `locate` extra is
not installed. Re-run `uv sync --project backend --extra dev --extra locate`
on the Windows machine, then reinstall the cu121 Torch wheels as shown above.
On an 11 GB 2080 Ti, FindMe unloads LocateAnything before SAM 2 propagation
and unloads SAM 2 before a rescue query so both models are not resident at the
same time.

NVIDIA licenses the LocateAnything weights for non-commercial research use
only. FindMe's text selection is therefore intended for personal/research use;
review NVIDIA's model license before using or redistributing the weights.

### Occlusion rescue does not activate

NVIDIA's currently published `nvidia/LocateAnything-3B` checkpoint does not
support visual-prompt inference. The rescue plumbing is implemented but remains
dormant until NVIDIA releases visual-prompt-capable weights. Text-prompt player
selection works independently of rescue.

### Native Windows model loading fails

LocateAnything's lightweight Transformers inference path is the intended
native-Windows setup, but NVIDIA primarily documents Linux environments. If
the remote model code fails on native Windows, run the same backend under
WSL2; the browser UI and local API contract are unchanged.

## Runtime boundaries

FindMe rejects cross-site browser requests and unexpected Host headers. The default
20 GiB multipart upload limit is enforced while streaming, and exports are limited to
4096×2160 (8,847,360 pixels), zoom 1–4, smoothing responsiveness 0–10 seconds, and
maximum acceleration 0.1–10,000 px/frame². Override the byte and dimension limits with
`FINDME_MAX_UPLOAD_BYTES`, `FINDME_MAX_EXPORT_WIDTH`,
`FINDME_MAX_EXPORT_HEIGHT`, and `FINDME_MAX_EXPORT_PIXELS`. Add non-IP LAN hostnames
with the comma-separated `FINDME_ALLOWED_HOSTS` setting.

Unexpected API failures return a stable error code and an `X-Request-ID`; the matching
identifier is written to the backend log with the full diagnostic traceback.

The reusable library is stored transactionally in
`data/library/findme.sqlite3` with SQLite WAL journaling and full synchronous writes.
This is a clean persistence-format break: legacy `videos.json`, `exports.json`, and
per-track JSON files are left untouched but are not imported.

## Known limitations

- Text selection requires NVIDIA CUDA. macOS and CPU hosts support click
  selection, tracking, crop planning, and export only.
- Visual-prompt occlusion rescue awaits compatible public weights.
- Tracking is single-player and can change identity during close interactions;
  recovery currently requires a new click and track job.
- Tracking and export each run through one worker with at most two queued jobs. A full
  queue returns HTTP 429, and `POST /api/jobs/{jobId}/cancel` cooperatively cancels a
  queued or running job.
- Job state is persisted in SQLite. Completed history is bounded; saved library tracks
  and exports remain available after history pruning, while work interrupted by a
  backend restart is reported as failed.
- FindMe is a local, single-user application with no authentication. Host/origin
  checks reduce browser-based cross-site requests but do not make LAN deployment a
  multi-user security boundary.

## Verification

```bash
cd backend && uv run --extra dev pytest -m 'not integration'
cd frontend && npm test && npm run typecheck && npm run build
```

See [docs/plan.md](docs/plan.md) for the architecture and milestone history.
