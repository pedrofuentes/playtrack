# M0 Scaffold and Video I/O Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the M0 FastAPI/Vite scaffold with video registration, metadata probing, byte-range playback, cached frame extraction, and source-pixel click coordinates.

**Architecture:** A focused `VideoStore` owns registered paths, uploads, ffprobe metadata, and an ffmpeg JPEG cache; FastAPI routes translate HTTP requests into that service. The React UI auto-registers the bundled example, uses native video controls, and maps overlay clicks through the rendered `object-fit: contain` rectangle with a pure tested geometry helper.

**Tech Stack:** Python 3.11/3.12, FastAPI, uvicorn, ffprobe/ffmpeg, pytest, React 19, TypeScript, Vite, Vitest.

## Global Constraints

- Stay within M0; do not add selection, tracking, crop planning, export, or model code.
- Support JSON `{path}` registration and multipart upload at `POST /api/videos`.
- Return `{videoId, width, height, fps, nbFrames, duration}` and serve byte ranges at `GET /api/videos/{id}/file`.
- Cache extracted JPEG frames at maximum dimension 2048 and retain source/cache scale metadata.
- Click coordinates must be in source pixels and reject clicks in letterbox padding.
- Keep Python support at `>=3.11,<3.13` as specified by the roadmap.

---

### Task 1: Backend video store and HTTP API

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `backend/app/videos.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_videos.py`

**Interfaces:**
- Consumes: local paths relative to the repository root, uploaded MP4 bytes, installed `ffprobe` and `ffmpeg` executables.
- Produces: `VideoMetadata`, `VideoRecord`, `VideoStore.register_path`, `VideoStore.register_upload`, `VideoStore.extract_frame`, and the M0 HTTP routes.

- [ ] **Step 1: Write failing API and service tests**

```python
def test_registers_local_video_and_returns_metadata(client, tiny_video):
    response = client.post("/api/videos", json={"path": str(tiny_video)})
    assert response.status_code == 201
    assert response.json()["width"] == 320
    assert response.json()["height"] == 180

def test_video_file_supports_byte_ranges(client, registered_video):
    response = client.get(
        f"/api/videos/{registered_video['videoId']}/file",
        headers={"Range": "bytes=0-31"},
    )
    assert response.status_code == 206
    assert len(response.content) == 32

def test_frame_extraction_is_cached(client, registered_video):
    first = client.get(f"/api/videos/{registered_video['videoId']}/frames/0")
    second = client.get(f"/api/videos/{registered_video['videoId']}/frames/0")
    assert first.status_code == second.status_code == 200
    assert first.content == second.content
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && python -m pytest tests/test_videos.py -q`

Expected: collection/import failure because `app.main` and the API do not exist.

- [ ] **Step 3: Implement the minimal backend**

Implement immutable Pydantic response models, fraction-safe fps parsing, validated ffprobe JSON, UUID registration, repository-relative path resolution, streamed upload persistence, cached ffmpeg frame extraction, FastAPI exception translation, CORS for the Vite dev origin, `FileResponse` byte-range serving, and a frame JPEG route exposing cache dimensions and scale headers.

- [ ] **Step 4: Run backend tests and verify GREEN**

Run: `cd backend && python -m pytest tests -q`

Expected: all backend tests pass.

### Task 2: React video player and coordinate overlay

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.app.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/vite-env.d.ts`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/api.ts`
- Create: `frontend/src/geometry.ts`
- Create: `frontend/src/geometry.test.ts`
- Create: `frontend/src/components/VideoStage.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/styles.css`

**Interfaces:**
- Consumes: `POST /api/videos`, `GET /api/videos/{id}/file`, browser video intrinsic dimensions, canvas CSS dimensions, pointer offsets.
- Produces: `sourcePointFromCanvas(...) -> {x, y} | null`, auto-loaded native video player, scrub/play/pause controls, and visible/logged source coordinates.

- [ ] **Step 1: Write failing geometry tests**

```ts
it('maps through horizontal letterboxing', () => {
  expect(sourcePointFromCanvas({x: 500, y: 250}, {width: 1000, height: 500}, {width: 4096, height: 1024}))
    .toEqual({x: 2048, y: 512})
})

it('ignores clicks in letterbox padding', () => {
  expect(sourcePointFromCanvas({x: 500, y: 20}, {width: 1000, height: 500}, {width: 4096, height: 1024}))
    .toBeNull()
})
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd frontend && npm test -- --run`

Expected: failure because `sourcePointFromCanvas` does not exist.

- [ ] **Step 3: Implement the coordinate helper and UI**

Use `scale = min(canvasWidth/sourceWidth, canvasHeight/sourceHeight)`, derive centered rendered bounds, reject padding clicks, then clamp and round mapped pixels. Auto-register `examples/example.mp4`, point `<video>` at the range endpoint, provide native controls, resize a pointer canvas to its CSS box, and show/log each accepted click.

- [ ] **Step 4: Run tests and build; verify GREEN**

Run: `cd frontend && npm test -- --run && npm run build`

Expected: all geometry tests pass and Vite produces `dist/`.

### Task 3: Developer setup and end-to-end smoke verification

**Files:**
- Create: `scripts/dev.sh`
- Modify: `.gitignore`
- Modify: `README.md`

**Interfaces:**
- Consumes: a Python 3.11/3.12 environment managed by uv, Node/npm, ffmpeg/ffprobe.
- Produces: one-command development startup instructions and reproducible curl checks.

- [ ] **Step 1: Add setup documentation and launcher**

Document `uv sync --project backend --extra dev`, `npm install --prefix frontend`, `scripts/dev.sh`, API endpoints, and coordinate behavior. The launcher starts FastAPI on port 8000 and Vite on port 5173 and cleans up both processes on exit.

- [ ] **Step 2: Run all automated verification**

Run: `cd backend && python -m pytest tests -q`

Run: `cd frontend && npm test -- --run && npm run build`

Expected: all tests and the production frontend build pass.

- [ ] **Step 3: Run a real-asset API smoke test**

Start uvicorn, register `examples/example.mp4`, verify 4096×1024 / 30 fps / 930 frames / 31 seconds, request `Range: bytes=0-99` and verify HTTP 206 with 100 bytes, then request frame 0 twice and verify an identical cached JPEG with maximum dimension 2048.

- [ ] **Step 4: Audit scope**

Re-read `docs/plan.md` M0 and confirm every M0 deliverable is represented while M1–M5 code is absent.
