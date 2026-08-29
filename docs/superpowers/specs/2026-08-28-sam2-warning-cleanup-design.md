# SAM 2 Warning Cleanup Design

## Problem

Native Windows tracking currently emits two avoidable warnings:

1. Click selection passes a read-only NumPy view from Pillow into torchvision,
   which warns that tensors backed by non-writable arrays have undefined write
   behavior.
2. The pinned SAM 2 package attempts to import its optional `sam2._C` CUDA
   extension for every mask post-processing call. The extension is absent on
   this machine because the Python environment has a CUDA-enabled PyTorch
   runtime but no CUDA toolkit/compiler toolchain. SAM 2 catches the import
   error and returns the unprocessed mask, but still emits a warning and pays
   the repeated exception cost.

The separate message that a 930-frame video tensor does not fit free VRAM is
an intentional safety guard. It must continue to enable both video and state
CPU offload on an RTX 2080 Ti instead of risking WDDM oversubscription and
another unresponsive desktop.

## Approved behavior

- Materialize click-selection RGB input as a writable, owned NumPy array before
  passing it to SAM 2.
- Probe the optional `sam2._C` extension once when constructing the video
  predictor. If it is unavailable or unusable, set only
  `predictor.fill_hole_area` to `0`; preserve SAM 2's other post-processing
  settings.
- Log one informational message when small-hole filling is disabled. Do not
  require or install a CUDA toolkit, Visual Studio compiler, WSL, or a new
  Python dependency.
- Preserve the automatic VRAM offload decision. Improve its warning to report
  the estimated video-tensor size, reserved headroom, and currently free VRAM.
- Keep every regression test weight-free, network-free, and GPU-free.
- Do not change `pyproject.toml` or `uv.lock`.

## Verification

- Focused tests must demonstrate the old behavior fails before production code
  changes and passes afterward.
- Run the full backend non-integration suite, frontend tests/typecheck/build,
  PWA tests, and static website validator before claiming completion.
