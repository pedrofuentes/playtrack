# SAM 2 Warning Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the writable-array and optional SAM 2 extension warnings while preserving the RTX 2080 Ti VRAM safety guard.

**Architecture:** Copy Pillow RGB pixels into an owned writable NumPy array at the selection boundary. Configure SAM 2's constructed video predictor once: retain all upstream post-processing when `sam2._C` loads, but disable only small-hole filling when the optional native extension cannot load. Keep the existing CPU-offload decision and make its diagnostic report the three memory quantities involved.

**Tech Stack:** Python 3.12, NumPy, Pillow, FastAPI backend, PyTorch/SAM 2, pytest

**Spec:** `docs/superpowers/specs/2026-08-28-sam2-warning-cleanup-design.md`

## Global Constraints

- The 930-frame RTX 2080 Ti safety path must still return `(True, True)` for video/state CPU offload when the tensor plus 3 GiB headroom exceeds free VRAM.
- Missing optional `sam2._C` support disables only `fill_hole_area`; SAM 2's dynamic multimask stability and memory-encoder post-processing remain untouched.
- Tests stay weight-free, network-free, and GPU-free.
- Do not edit `pyproject.toml` or `uv.lock`.
- Do not modify or delete runtime `data/`, `exports/`, `checkpoints/`, or the supplied `examples/example.mp4`.
- Use strict test-driven development: write and run the failing regression test before changing production code.

---

### Task 1: Pass writable RGB pixels to click selection

**Files:**
- Create: `backend/tests/test_selection.py`
- Modify: `backend/app/selection.py:96-99`

**Interfaces:**
- Consumes: `ClickSelector.select_click(video_id: str, frame_idx: int, x: int, y: int) -> ClickSelection`
- Produces: the existing `SelectionEngine.predict(image, point_x, point_y)` boundary now always receives an owned, C-contiguous, writable RGB `uint8` NumPy array.

- [ ] **Step 1: Write the failing regression test**

Create `backend/tests/test_selection.py` with a tiny real Pillow image, a fake store that returns the complete metadata/path shape consumed by `ClickSelector`, and a recording engine whose real result drives the rest of selection:

```python
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

from app.models.sam2_engine import SAM2Prediction
from app.selection import ClickSelector


class RecordingEngine:
    def __init__(self) -> None:
        self.image: np.ndarray | None = None

    def predict(self, image: object, point_x: int, point_y: int) -> SAM2Prediction:
        assert isinstance(image, np.ndarray)
        self.image = image
        mask = np.zeros(image.shape[:2], dtype=bool)
        mask[point_y, point_x] = True
        return SAM2Prediction(mask=mask, score=0.9)


class TinyVideoStore:
    def __init__(self, image_path: Path) -> None:
        self.image_path = image_path

    def get(self, video_id: str) -> object:
        return SimpleNamespace(metadata=SimpleNamespace(width=4, height=3))

    def extract_source_crop(self, *args: object, **kwargs: object) -> object:
        return SimpleNamespace(path=self.image_path)


def test_click_selector_passes_writable_owned_rgb_array(tmp_path: Path) -> None:
    image_path = tmp_path / "crop.png"
    Image.new("RGB", (4, 3), (10, 20, 30)).save(image_path)
    engine = RecordingEngine()
    selector = ClickSelector(
        TinyVideoStore(image_path), engine_provider=lambda: engine, crop_size=4
    )

    selector.select_click("video-1", frame_idx=0, x=1, y=1)

    assert engine.image is not None
    assert engine.image.dtype == np.uint8
    assert engine.image.flags.c_contiguous
    assert engine.image.flags.writeable
    assert engine.image.base is None
```

This test catches replacing the owned copy with `np.asarray(...)` or another read-only/view-producing conversion.

- [ ] **Step 2: Run the test and verify RED**

From `backend/`, set the repository's ffmpeg shim inside the Python process
(the managed Windows runner normalizes child-process `PATH`) and run:

```powershell
.\.venv\Scripts\python.exe -c "import os; scratch=os.path.abspath(r'.venv\tmp'); os.environ['PATH']=r'S:\Pedro\Projects\playtrack\.tools\ffmpeg\bin;' + os.environ['PATH']; os.environ['TEMP']=scratch; os.environ['TMP']=scratch; import pytest; raise SystemExit(pytest.main(['tests/test_selection.py', '-q', '--basetemp', os.path.join(scratch, 'pytest-task1-red')]))"
```

Expected: FAIL because `engine.image.flags.writeable` is `False` (and/or `base` is not `None`) against the current `np.asarray(source_image.convert("RGB"))` implementation.

- [ ] **Step 3: Make the minimal production change**

In `ClickSelector.select_click`, replace the conversion with:

```python
with Image.open(extracted.path) as source_image:
    rgb_image = np.array(source_image.convert("RGB"), copy=True)
```

- [ ] **Step 4: Run focused tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -c "import os; scratch=os.path.abspath(r'.venv\tmp'); os.environ['PATH']=r'S:\Pedro\Projects\playtrack\.tools\ffmpeg\bin;' + os.environ['PATH']; os.environ['TEMP']=scratch; os.environ['TMP']=scratch; import pytest; raise SystemExit(pytest.main(['tests/test_selection.py', 'tests/test_selection_geometry.py', 'tests/test_select_api.py', '-q', '--basetemp', os.path.join(scratch, 'pytest-task1-green')]))"
```

Expected: all selected tests pass without the non-writable NumPy warning.

- [ ] **Step 5: Commit the task**

```powershell
git add -- backend/app/selection.py backend/tests/test_selection.py
git commit -m "Pass writable image arrays to SAM 2"
```

---

### Task 2: Disable unavailable optional SAM 2 hole filling once

**Files:**
- Modify: `backend/app/models/sam2_engine.py:1-55,333-365`
- Modify: `backend/tests/test_sam2_engine.py`
- Modify: `AGENTS.md` under `Known pitfalls`

**Interfaces:**
- Consumes: `build_sam2_video_predictor(...)` and its returned `fill_hole_area` attribute; optional module `sam2._C` with callable `get_connected_componnets` (upstream spelling).
- Produces: `_sam2_cuda_extension_available() -> bool`; constructed predictors retain `fill_hole_area == 8` when the native extension works and receive `fill_hole_area == 0` when it does not.
- Preserves: `resolve_video_offload(...) -> tuple[bool, bool]` decisions while enriching its warning text.

- [ ] **Step 1: Write failing extension and predictor-wiring tests**

Extend `backend/tests/test_sam2_engine.py` with tests that monkeypatch `importlib.import_module` for deterministic optional-extension outcomes:

```python
def test_sam2_cuda_extension_probe_rejects_missing_module(monkeypatch) -> None:
    def missing(name: str) -> object:
        raise ImportError(name)

    monkeypatch.setattr(sam2_engine.importlib, "import_module", missing)
    assert sam2_engine._sam2_cuda_extension_available() is False


def test_sam2_cuda_extension_probe_accepts_connected_components(monkeypatch) -> None:
    extension = SimpleNamespace(get_connected_componnets=lambda *_args: None)
    monkeypatch.setattr(
        sam2_engine.importlib, "import_module", lambda name: extension
    )
    assert sam2_engine._sam2_cuda_extension_available() is True
```

Add a predictor-construction test using `types.ModuleType` and `monkeypatch.setitem(sys.modules, ...)` to supply a fake `sam2.build_sam.build_sam2_video_predictor`. The fake builder returns:

```python
predictor = SimpleNamespace(
    fill_hole_area=8,
    dynamic_multimask_via_stability=True,
    binarize_mask_from_pts_for_mem_enc=True,
)
```

Create a real empty checkpoint file, force a CPU `DeviceProfile`, patch `_sam2_cuda_extension_available` to `False`, call `_ensure_predictor(fake_torch())`, and assert:

```python
assert predictor.fill_hole_area == 0
assert predictor.dynamic_multimask_via_stability is True
assert predictor.binarize_mask_from_pts_for_mem_enc is True
```

Add a symmetric available-extension case asserting `fill_hole_area == 8`.

- [ ] **Step 2: Write a failing VRAM diagnostic test**

Using `caplog`, call `resolve_video_offload` for 930 frames, `image_size=1024`, and `free_vram_bytes=9_603 * 1024**2`. Assert the result remains `(True, True)` and the single warning contains `11160 MiB video tensor`, `3072 MiB headroom`, and `9603 MiB free VRAM`.

- [ ] **Step 3: Run the tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -c "import os; scratch=os.path.abspath(r'.venv\tmp'); os.environ['PATH']=r'S:\Pedro\Projects\playtrack\.tools\ffmpeg\bin;' + os.environ['PATH']; os.environ['TEMP']=scratch; os.environ['TMP']=scratch; import pytest; raise SystemExit(pytest.main(['tests/test_sam2_engine.py', '-q', '--basetemp', os.path.join(scratch, 'pytest-task2-red')]))"
```

Expected: FAIL because the extension probe does not exist, the constructed predictor still has `fill_hole_area == 8`, and the current warning omits tensor/headroom quantities.

- [ ] **Step 4: Implement the optional-extension probe**

Import `importlib` and add this private helper near the other pure detection helpers:

```python
def _sam2_cuda_extension_available() -> bool:
    try:
        extension = importlib.import_module("sam2._C")
    except (ImportError, OSError):
        return False
    return callable(getattr(extension, "get_connected_componnets", None))
```

- [ ] **Step 5: Configure the predictor once after construction**

Build into a local `predictor`. When `getattr(predictor, "fill_hole_area", 0) > 0` and the probe is false, set only `predictor.fill_hole_area = 0` and emit one `logger.info` message explaining that optional small-hole filling is disabled. Assign the configured object to `self._predictor`. Do not pass `apply_postprocessing=False`, because that would also disable dynamic multimask stability and memory-encoder binarization.

- [ ] **Step 6: Clarify the existing offload warning without changing its decision**

Calculate:

```python
tensor_mib = frame_count * 3 * image_size * image_size * 4 // 1024**2
headroom_mib = _VIDEO_OFFLOAD_HEADROOM_BYTES // 1024**2
free_mib = free_vram_bytes // 1024**2
```

Log one warning in the form:

```text
SAM2 safety guard: 11160 MiB video tensor plus 3072 MiB headroom exceeds 9603 MiB free VRAM; enabling CPU offload
```

Keep the return value `(True, True)` unchanged.

- [ ] **Step 7: Document the Windows compatibility behavior**

Add a `Known pitfalls` bullet to `AGENTS.md`: native Windows environments may lack SAM 2's optional `sam2._C` CUDA extension; PlayTrack then disables only the small-hole fill while preserving other post-processing, and setup must not grow a CUDA-toolkit/compiler requirement merely to enable it.

- [ ] **Step 8: Run focused tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -c "import os; scratch=os.path.abspath(r'.venv\tmp'); os.environ['PATH']=r'S:\Pedro\Projects\playtrack\.tools\ffmpeg\bin;' + os.environ['PATH']; os.environ['TEMP']=scratch; os.environ['TMP']=scratch; import pytest; raise SystemExit(pytest.main(['tests/test_sam2_engine.py', 'tests/test_tracking.py', 'tests/test_tracking_config.py', '-q', '--basetemp', os.path.join(scratch, 'pytest-task2-green')]))"
```

Expected: all selected tests pass with no SAM 2 `_C` warning.

- [ ] **Step 9: Commit the task**

```powershell
git add -- backend/app/models/sam2_engine.py backend/tests/test_sam2_engine.py AGENTS.md docs/superpowers/specs/2026-08-28-sam2-warning-cleanup-design.md docs/superpowers/plans/2026-08-28-sam2-warning-cleanup.md
git commit -m "Handle optional SAM 2 CUDA post-processing"
```
