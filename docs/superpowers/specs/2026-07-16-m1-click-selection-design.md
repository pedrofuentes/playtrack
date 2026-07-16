# M1 Click-to-Select Design

## Scope

M1 adds click-prompted SAM 2.1 image segmentation only. It does not start a
tracking job or add video propagation. The UI may expose a Track button, but
that button only explains that tracking arrives in M2.

## Backend architecture

`VideoStore` extracts an exact, cached source-resolution crop around a click
with ffmpeg. The crop is at most 1024×1024, centered when possible, clamped to
the source frame, and uses exact chroma coordinates. It does not reuse M0's
downscaled frame cache because a hockey player would lose too much detail.

`selection.py` owns pure crop/source coordinate transforms and the selection
pipeline. It supplies the cropped RGB image and crop-local positive click to an
engine, chooses the engine result, translates the mask bounds to source space,
and encodes the crop mask into a full-source transparent RGBA PNG.

`models/sam2_engine.py` imports Torch, NumPy, and SAM 2 only when prediction is
first requested. `get_sam2_engine()` is a cached singleton provider, while the
engine separately lazy-loads the official `SAM2ImagePredictor`. A lock protects
the predictor's mutable `set_image` state.

Device detection follows the plan: CUDA Turing uses fp16, CUDA Ampere or newer
uses bf16, MPS uses fp32 for compatibility, and CPU uses fp32. The profile also
reports the matrix-recommended model size, while the configured/default M1
checkpoint remains SAM 2.1 base-plus.

## API and data flow

`POST /api/select/click` accepts integer source coordinates:

```json
{"videoId":"...","frameIdx":0,"x":2048,"y":512}
```

It returns:

```json
{
  "box":[2000,470,2050,535],
  "maskPng":"<raw base64 PNG>",
  "score":0.94
}
```

`box` is source-space XYXY with exclusive `x2`/`y2`. `maskPng` decodes to a
full-source-size transparent RGBA image, with the selected mask tinted teal.
Unknown videos return 404, invalid frames/clicks and empty masks return 422,
and missing dependencies/checkpoints return 503.

## Frontend

`VideoStage` reports the displayed frame index with each source click. `App`
posts the click, cancels stale requests, and passes the selection back to the
stage. A full-size transparent mask image uses the same `object-fit: contain`
geometry as the video, while the existing canvas draws the source-space box.
The sidebar shows selection progress/errors, score, and a visible M2 Track stub.

## Models and setup

`scripts/fetch_models.py` downloads official SAM 2.1 checkpoint URLs into
`checkpoints/`, selecting base-plus by default and supporting every official
size or all sizes. It writes through a `.part` file and does not overwrite an
existing checkpoint unless `--force` is supplied.

The backend declares Torch, TorchVision, the official SAM-2 Git dependency,
NumPy, Pillow, and headless OpenCV. The uv lock cannot be refreshed in this
sandbox because the new packages and Git repository are unavailable here; an
online `uv sync --extra dev` performs that resolution outside the sandbox.

## Testing

Weight-free tests cover crop clamping, source/crop transforms, device profile
selection with a fake Torch module, the API response contract through an
injected fake selector, the frontend request body, displayed-frame math, and
source-box canvas mapping. A marked integration test is skipped unless the
configured checkpoint exists and then exercises the full selector on the real
example video.

