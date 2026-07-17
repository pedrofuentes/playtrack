# FindMe

Select a player in a sports video, track them, and export a cropped "virtual camera" video that follows them.

See [docs/plan.md](docs/plan.md) for the full roadmap and implementation spec.

## M0: scaffold and video I/O

The M0 app registers a local video or upload, probes its metadata with
`ffprobe`, streams it with HTTP byte-range support, and extracts exact frames
into a downscaled JPEG cache. The React player opens
`examples/example.mp4` automatically and reports clicks in source-video pixels,
including when the panorama is letterboxed inside the player.

### Requirements

- Python 3.11 or 3.12
- [uv](https://docs.astral.sh/uv/)
- Node.js 20 or newer with npm
- `ffmpeg` and `ffprobe` on `PATH`

### Install and run

```bash
uv sync --project backend --extra dev
npm install --prefix frontend
./scripts/dev.sh
```

Open <http://127.0.0.1:5173>. Native video controls provide play, pause, and
scrubbing. Click inside the visible picture to display a source-pixel position;
the same `{x, y}` value is written to the browser console. Clicks in the blank
letterbox area are ignored.

Build the frontend before starting only the backend to serve the production UI
from <http://127.0.0.1:8000>:

```bash
npm run build --prefix frontend
cd backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### API smoke checks

With the backend running from `backend/`, paths are still resolved from the
repository root:

```bash
curl -sS -X POST http://127.0.0.1:8000/api/videos \
  -H 'Content-Type: application/json' \
  -d '{"path":"examples/example.mp4"}'

curl -i http://127.0.0.1:8000/api/videos/VIDEO_ID/file \
  -H 'Range: bytes=0-99'

curl -o frame.jpg http://127.0.0.1:8000/api/videos/VIDEO_ID/frames/0

curl -sS -X POST http://127.0.0.1:8000/api/videos \
  -F 'file=@examples/example.mp4'
```

The example metadata is 4096×1024, 30 fps, 930 frames, and 31 seconds. Cached
frames retain the source aspect ratio with a maximum dimension of 2048; response
headers report their dimensions and source scale.

## M1: click-to-select

Install the updated backend dependencies, then download the default SAM 2.1
base-plus checkpoint:

```bash
uv sync --project backend --extra dev
python scripts/fetch_models.py
```

Clicking the video sends the displayed frame and source-pixel coordinate to
`POST /api/select/click`. Selection runs on an exact 1024×1024 source crop so
small players in the panorama retain useful detail. The returned transparent
mask and source-space box are drawn over the player and become the M2 tracking
anchor.

## M2: video tracking

After selecting a player, choose **Track this player** to start bidirectional
SAM 2 propagation. The UI receives partial results over a WebSocket and draws
the current frame's tracked box while the video plays or scrubs. Tracking jobs
are also available through `POST /api/track`, `GET /api/track/{jobId}`, and
`WS /ws/jobs/{jobId}`.

Tracking uses its own sequential JPEG cache rather than the UI thumbnail
cache. Its maximum source dimension defaults to 2048 and can be raised for
small subjects in high-resolution panoramas:

```bash
TRACKING_MAX_DIM=4096 ./scripts/dev.sh
```

Low-memory machines can independently offload decoded video frames and SAM 2
state to system memory:

```bash
SAM2_OFFLOAD_VIDEO_TO_CPU=true SAM2_OFFLOAD_STATE_TO_CPU=true ./scripts/dev.sh
```

## M3: crop planning and export

Completed tracks expose a virtual-camera export panel with 1920×1080,
1280×720, and custom output sizes. Zoom, dead-zone, smoothing-window, and pan
speed controls update a source-space crop preview on the video. Exports run as
background jobs and produce H.264/yuv420p MP4 files under the ignored
`exports/` directory; source audio is carried into the result.

The supporting endpoints are:

- `GET /api/export/plan` for read-only per-frame crop windows.
- `POST /api/export` to start a background export job.
- `GET /api/exports/{jobId}.mp4` to download a completed result.
- `WS /ws/jobs/{jobId}` for export progress, shared with tracking jobs.

## M4: LocateAnything on Windows / RTX 2080 Ti

Text-prompt selection and occlusion rescue use
`nvidia/LocateAnything-3B`. The feature is CUDA-only: it is hidden in the UI
and `POST /api/select/text` returns a clear `501` response on Mac/CPU hosts.
On a Windows machine with an RTX 2080 Ti, create the environment and then
replace the generic Torch install with NVIDIA's CUDA 12.1 wheels:

```powershell
uv sync --project backend --extra dev --extra locate
uv pip install --python backend\.venv\Scripts\python.exe --reinstall `
  "torch>=2.5.1,<3" "torchvision>=0.20.1,<1" `
  --index-url https://download.pytorch.org/whl/cu121
```

The `locate` extra pins `transformers==4.57.1`; it is intentionally omitted
from normal Mac installs. The first text-selection or rescue request downloads
approximately 7.7 GB of model weights from Hugging Face. LocateAnything runs
in fp16 with PyTorch SDPA on Turing cards such as the 2080 Ti (Ampere and newer
use bf16).

An 11 GB card cannot safely keep LocateAnything and SAM 2 resident together.
The tracker therefore unloads LocateAnything before initial SAM propagation,
unloads SAM before a rescue query, and unloads LocateAnything again before
re-seeding SAM. `torch.cuda.empty_cache()` is called at each model handoff.
Rescue behavior can be tuned with `LOCATE_RESCUE_AFTER` (default `15`) and
`LOCATE_RESCUE_MIN_SCORE` (default `0.5`), or disabled with
`LOCATE_RESCUE_ENABLED=false`. `LOCATE_MAX_INPUT_DIM` defaults to `2500`;
larger source frames are resized for inference and returned boxes are mapped
back to source pixels.

LocateAnything weights are licensed by NVIDIA for non-commercial research use
only. Review the model license before use or redistribution. NVIDIA also notes
that the currently published base checkpoint does not yet provide supported
visual-prompt inference; text grounding works with that checkpoint, while the
rescue path requires visual-prompt-capable weights when NVIDIA releases them.

### Checks

```bash
cd backend && uv run --extra dev pytest -m 'not integration'
cd frontend && npm test && npm run typecheck && npm run build
```
