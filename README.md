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

### Checks

```bash
cd backend && uv run --extra dev pytest
cd frontend && npm test && npm run typecheck && npm run build
```
