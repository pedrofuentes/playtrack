# Windows CUDA & Portability Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. If those skills are unavailable in your harness (e.g. Codex), execute the tasks strictly in order, checking off each step.

**Goal:** Make PlayTrack safe and reproducible on the Windows/RTX 2080 Ti target: `uv sync` installs CUDA torch, SAM 2 can never freeze the machine by overcommitting VRAM, and the full backend test suite is green on Windows.

**Architecture:** Five code/config fixes plus a docs pass, ordered so the Python environment is stabilized first (everything after runs under `uv run`, which auto-syncs the venv to the lockfile). Product-code fixes are platform-neutral — no `if windows` branches; they fix genuine bugs that POSIX happened to tolerate.

**Tech Stack:** FastAPI + Starlette, uv (lockfile-driven), PyTorch cu124 wheels, sqlite3 stdlib, pytest.

**Spec:** the **Background** section below — this plan is self-contained; you need no other document.

**Provenance:** adversarially reviewed by Codex (gpt-5.6-sol) on 2026-08-28; all findings incorporated.

## Background (read before Task 1)

This machine (Windows, RTX 2080 Ti, 11,264 MiB VRAM, sm_75) completed a full bring-up on 2026-08-28. Findings this plan fixes:

1. **`uv sync` installs CPU-only torch on Windows.** `uv.lock` resolves torch 2.13.0/torchvision 0.28.0 from PyPI, whose Windows wheels are CPU-only. CUDA was obtained by manually installing `torch==2.6.0+cu124` / `torchvision==0.21.0+cu124` from `https://download.pytorch.org/whl/cu124` — and **any `uv run`/`uv sync` will revert that to CPU wheels**, because uv syncs the venv to the lock before running. This is why Task 1 comes first. (The README's manual-install instructions even point at a different, stale index — cu121/torch 2.5.1 — and are corrected in Task 6.)
2. **The no-offload default froze this machine.** SAM 2's `init_state` stacks the whole video as one float32 `[N, 3, 1024, 1024]` tensor and transfers it to the GPU: 930 frames ≈ 11,160 MiB — not larger than the card's 11,264 MiB total, but it leaves ~104 MiB, so it cannot coexist with the already-loaded model and runtime (~2,900 MiB baseline). Windows/WDDM then oversubscribes GPU memory, utilization drops to ~0%, the desktop freezes, and the NVIDIA driver needs a reboot. With `SAM2_OFFLOAD_VIDEO_TO_CPU=1` + `SAM2_OFFLOAD_STATE_TO_CPU=1` the same track peaks at 4,253 MiB and finishes 930 frames in 3m13s (~4.8 fps). The code currently force-offloads on MPS only (`backend/app/models/sam2_engine.py`, inside `SAM2VideoEngine.propagate`).
   **Safety caveat:** the allocation happens entirely inside `init_state`, *before* the tracking loop yields its first frame. Job cancellation (`POST /api/jobs/{id}/cancel`) is only observed at per-frame progress reports, so **cancellation cannot interrupt a bad allocation** — the only remedy once it starts is killing the backend process. Task 5's verification is designed around that fact.
3. **17 backend test failures on Windows**, three classes:
   - 4 × legacy SQLite migration tests: `PermissionError: [WinError 32]` — real bug, `backend/app/library.py` (`_migrate_legacy_database`) leaves sqlite3 connections open during `Path.replace`/`unlink` (`with sqlite3.connect(...)` manages transactions, **not** closing).
   - 2 × SPA-routing tests (`tests/test_frontend_serving.py::test_api_routes_take_precedence_and_missing_assets_do_not_fall_back`, `tests/test_security.py::test_every_http_response_has_server_generated_request_id`): missing `/api/*` paths return 200 (the SPA page) instead of 404 — real bug. Starlette's `StaticFiles.get_path()` normalizes the route-relative URL path with `os.path.normpath` ("with OS specific path separators" per its docstring), so on Windows `SPAStaticFiles._is_spa_route` in `backend/app/main.py` receives `api\not-a-route`, its `"/"`-based first-segment check misses `api`, and it serves `index.html`.
   - 10 × `tests/test_unix_dev_script.py`: `FileNotFoundError: [WinError 2]` — they invoke `/bin/bash` and must skip on Windows; plus 1 × `tests/test_brand_assets.py::test_brand_builder_emits_expected_assets_and_dimensions`: compares `str(path.relative_to(...))` (backslashes on Windows) against POSIX literals.

## Global Constraints

- All PowerShell commands in this plan are written for Windows PowerShell 5.1 compatibility (no `&&` chaining). If you have PowerShell 7, they still work.
- Work on a branch:
  ```powershell
  git fetch origin
  git switch -c fix/windows-cuda-and-portability origin/main
  ```
  **Never commit to main; push the branch and stop** — the Mac maintainer re-runs the POSIX suite and merges.
- The unmarked pytest suite must never depend on model weights, network, or GPUs; `integration`-marked tests must skip cleanly when weights/CUDA are absent.
- All backend commands run from `backend/`. The default gate is `uv run --extra dev pytest -m "not integration"`.
- **Until Task 1 is committed, do not run `uv run`/`uv sync`** (it will replace the manually installed CUDA torch with CPU wheels). If you must run something first, use `uv run --no-sync`.
- Keep `uv.lock` in sync via uv commands only; never hand-edit it.
- Never commit `data/`, `exports/`, `checkpoints/`. Leave `frontend/package-lock.json` alone (its mtime/stat noise is known; `git diff` is empty).
- Product code must stay platform-neutral: fix bugs, don't add `sys.platform == "win32"` branches to `app/`, and don't import private Starlette modules.
- Commit subjects: plain imperative, no prefixes (repo convention), e.g. `Close SQLite connections before migration file operations`.
- Python 3.12 (`requires-python >=3.11,<3.13`).

---

### Task 1: Install CUDA torch on Windows via a uv index

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock` (via `uv lock` only)

**Interfaces:**
- Produces: a venv where `torch.cuda.is_available()` is `True` after any plain `uv sync --extra dev` on Windows; macOS/Linux resolution unchanged (torch 2.13.0 / torchvision 0.28.0 from PyPI).

- [ ] **Step 1: Record the current (broken) behavior**

Run (PowerShell, from `backend/`):
```powershell
uv run --no-sync python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```
Expected: `2.6.0+cu124 True` (the manual install from the bring-up). This is the state a plain `uv sync` would destroy today.

- [ ] **Step 2: Add the cu124 index to `pyproject.toml`**

Append to `backend/pyproject.toml` (after the `[tool.hatch.metadata]` section, before `[tool.pytest.ini_options]`):

```toml
[tool.uv.sources]
torch = [{ index = "pytorch-cu124", marker = "sys_platform == 'win32'" }]
torchvision = [{ index = "pytorch-cu124", marker = "sys_platform == 'win32'" }]

[[tool.uv.index]]
name = "pytorch-cu124"
url = "https://download.pytorch.org/whl/cu124"
explicit = true
```

Why cu124 and not a newer index: `torch 2.6.0+cu124` / `torchvision 0.21.0+cu124` are the exact wheels already proven on this GPU (sm_75) during bring-up. Newer CUDA indexes ship newer torch lines that are unproven on Turing here — upgrading is a separate, deliberate experiment, not part of this plan. The resulting version skew (Windows 2.6.0+cu124 vs macOS 2.13.0 PyPI) is accepted and documented in Task 6.

- [ ] **Step 3: Re-lock and inspect the diff**

```powershell
uv lock
git diff --stat uv.lock
git diff uv.lock | Select-String '^[-+](version|source)' | Select-Object -First 40
```
Expected: torch/torchvision gain `sys_platform == 'win32'` forks resolving `2.6.0+cu124` / `0.21.0+cu124` from `https://download.pytorch.org/whl/cu124`; the non-Windows forks keep `2.13.0` / `0.28.0` from PyPI. **If the non-Windows torch/torchvision versions changed, or unrelated packages changed version, stop: `git checkout uv.lock`, retry with `uv lock`, and if it persists, report instead of committing.**

- [ ] **Step 4: Sync and verify CUDA survives a real sync**

```powershell
uv sync --extra dev
uv run python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```
Expected: `2.6.0+cu124 12.4 True NVIDIA GeForce RTX 2080 Ti`.

- [ ] **Step 5: Verify the weight-free suite still collects and runs**

```powershell
uv run --extra dev pytest -m "not integration" -q
```
Expected: same failure set as bring-up (17 failed — they are fixed by Tasks 2–4), no new errors, no import errors.

- [ ] **Step 6: Commit**

```powershell
git add pyproject.toml uv.lock
git commit -m "Install CUDA torch wheels on Windows via uv index"
```

---

### Task 2: Close SQLite connections before migration file operations

**Files:**
- Modify: `backend/app/library.py` (function `_migrate_legacy_database`, near the top of the file)
- Test: `backend/tests/test_sqlite_library.py` (existing tests — they are the red)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `_migrate_legacy_database(root: Path) -> None` with identical signature and behavior, but no file handles open when `partial.replace(canonical)` / `partial.unlink()` run.

- [ ] **Step 1: Run the failing tests (red)**

```powershell
uv run --extra dev pytest tests/test_sqlite_library.py -q -k "legacy"
```
Expected: 4 failures — `test_legacy_database_is_backed_up_into_canonical_path`, `test_legacy_migration_includes_committed_wal_records`, `test_canonical_database_wins_after_legacy_migration`, `test_failed_legacy_migration_cleans_partial_database` — with `PermissionError: [WinError 32]`.

- [ ] **Step 2: Fix the connection lifetimes**

In `backend/app/library.py`, add to the imports at the top of the file:

```python
from contextlib import closing
```

Then replace the body of `_migrate_legacy_database` so every connection is closed before any rename/unlink. The current code uses `with sqlite3.connect(...)`, which commits/rolls back but **never closes**; keep the transaction semantics with an inner `with target:` and add `closing(...)` for the lifetime:

```python
def _migrate_legacy_database(root: Path) -> None:
    canonical = root / _CANONICAL_DATABASE
    legacy = root / _LEGACY_DATABASE
    if canonical.exists() or not legacy.exists():
        return

    partial = root / f"{_CANONICAL_DATABASE}{_MIGRATION_SUFFIX}"
    partial.unlink(missing_ok=True)
    try:
        source_uri = f"{legacy.resolve().as_uri()}?mode=ro"
        # sqlite3.connect used as a context manager only manages the
        # transaction; the connection must be closed explicitly or Windows
        # keeps the files locked during replace()/unlink() below (WinError 32).
        with closing(sqlite3.connect(source_uri, uri=True, timeout=5.0)) as source:
            with closing(sqlite3.connect(partial, timeout=5.0)) as target:
                with target:
                    _backup_database(source, target)
        with closing(sqlite3.connect(partial, timeout=5.0)) as migrated:
            result = migrated.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            detail = "no result" if result is None else str(result[0])
            raise RuntimeError(f"Legacy library migration failed integrity check: {detail}")
        partial.replace(canonical)
        logger.info("Migrated legacy library database to %s", canonical)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
```

- [ ] **Step 3: Run the tests (green)**

```powershell
uv run --extra dev pytest tests/test_sqlite_library.py tests/test_library.py -q
```
Expected: all pass, including the four migration tests.

- [ ] **Step 4: Commit**

```powershell
git add app/library.py
git commit -m "Close SQLite connections before migration file operations"
```

---

### Task 3: Judge SPA fallback routes with URL separators, not filesystem separators

**Files:**
- Modify: `backend/app/main.py` (`SPAStaticFiles._is_spa_route`, around line 107)
- Test: `backend/tests/test_frontend_serving.py` (one new unit test + existing tests), `backend/tests/test_security.py` (existing test)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `SPAStaticFiles` with unchanged public behavior on POSIX; on Windows, missing `/api/*`, `/assets/*`, `/ws/*` paths now 404 instead of serving the SPA.

Design note (do not re-litigate): the fix normalizes the `path` argument's separators rather than reading `scope["path"]` or importing Starlette's private `starlette._utils.get_route_path`. The `path` argument is already the **route-relative** result of `get_route_path` (so an ASGI `root_path` is already stripped) — its only problem is that `os.path.normpath` gave it OS separators. `scope["path"]` would break behind a root_path; the private import would be fragile.

- [ ] **Step 1: Add the failing unit test (red on every platform)**

In `backend/tests/test_frontend_serving.py`, extend the import to `from app.main import SPAStaticFiles, create_app` and append:

```python
def test_spa_route_check_rejects_windows_normalized_api_paths() -> None:
    # Starlette's StaticFiles.get_path() applies os.path.normpath, so on
    # Windows the path arrives with backslash separators.
    scope = {"method": "GET", "path": "/api/not-a-route"}
    assert not SPAStaticFiles._is_spa_route("api\\not-a-route", scope)
```

- [ ] **Step 2: Run the failing tests (red)**

```powershell
uv run --extra dev pytest "tests/test_frontend_serving.py::test_spa_route_check_rejects_windows_normalized_api_paths" "tests/test_frontend_serving.py::test_api_routes_take_precedence_and_missing_assets_do_not_fall_back" "tests/test_security.py::test_every_http_response_has_server_generated_request_id" -q
```
Expected: all three fail (the new unit test fails on any platform; the two HTTP tests fail on Windows with `assert 200 == 404`).

- [ ] **Step 3: Fix `_is_spa_route`**

In `backend/app/main.py`, replace the `_is_spa_route` static method of `SPAStaticFiles` with:

```python
    @staticmethod
    def _is_spa_route(path: str, scope: dict[str, Any]) -> bool:
        if scope.get("method") not in ("GET", "HEAD"):
            return False
        # Starlette's StaticFiles.get_path() runs os.path.normpath on the
        # route-relative URL path, so on Windows `path` arrives with
        # backslash separators; restore URL separators before judging
        # segments.
        normalized = path.replace("\\", "/").lstrip("/")
        first_segment = normalized.partition("/")[0]
        if first_segment in {"api", "assets", "ws"}:
            return False
        return posixpath.splitext(normalized)[1] == ""
```

(The only change is the `normalized = ...` line and the comment; method signature, decorator, and the rest stay identical. `posixpath` is already imported in `main.py`.)

- [ ] **Step 4: Run the tests (green), including the SPA deep-link test that must keep passing**

```powershell
uv run --extra dev pytest tests/test_frontend_serving.py tests/test_security.py -q
```
Expected: all pass — deep links (`/tracks/example`) still serve the SPA; missing `/api/*` and `/assets/*` return 404.

- [ ] **Step 5: Commit**

```powershell
git add app/main.py tests/test_frontend_serving.py
git commit -m "Judge SPA fallback routes with URL separators, not filesystem separators"
```

---

### Task 4: Make launcher and brand-asset tests Windows-portable

**Files:**
- Modify: `backend/tests/test_unix_dev_script.py`
- Modify: `backend/tests/test_brand_assets.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: on Windows, `test_unix_dev_script.py` reports 10 skips; `test_brand_builder_emits_expected_assets_and_dimensions` passes. On POSIX, nothing changes (the Mac maintainer verifies).

- [ ] **Step 1: Run the failing tests (red)**

```powershell
uv run --extra dev pytest tests/test_unix_dev_script.py tests/test_brand_assets.py -q
```
Expected: 10 × `FileNotFoundError: [WinError 2]` (spawning `/bin/bash`) and 1 × set-comparison failure with backslashed paths.

- [ ] **Step 2: Skip the POSIX launcher tests on non-POSIX platforms**

In `backend/tests/test_unix_dev_script.py`, add `import pytest` alongside the existing imports and a module-level mark right after the imports (before `REPO_ROOT = ...`):

```python
import pytest

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="dev.sh launcher tests spawn /bin/bash and POSIX stub scripts",
)
```

(`os` is already imported in that file.)

- [ ] **Step 3: Compare brand output paths as POSIX strings**

In `backend/tests/test_brand_assets.py`, in `test_brand_builder_emits_expected_assets_and_dimensions`, replace:

```python
    assert {str(path.relative_to(repo_root)) for path in outputs} == set(expected)
```

with:

```python
    assert {path.relative_to(repo_root).as_posix() for path in outputs} == set(expected)
```

The `expected` dict keys and the later `repo_root / relative` lookups already work on both platforms — do not change them.

- [ ] **Step 4: Run the tests (green)**

```powershell
uv run --extra dev pytest tests/test_unix_dev_script.py tests/test_brand_assets.py -q
```
Expected: 10 skipped, brand tests pass, 0 failed.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_unix_dev_script.py tests/test_brand_assets.py
git commit -m "Skip POSIX launcher tests on Windows and compare brand paths as POSIX"
```

---

### Task 5: Auto-enable SAM2 CPU offload when the video tensor cannot fit CUDA memory

**Files:**
- Modify: `backend/app/models/sam2_engine.py`
- Test: `backend/tests/test_sam2_engine.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces (new module-level functions in `app/models/sam2_engine.py`, importable weight-free):
  - `video_fits_in_vram(frame_count: int, *, image_size: int, free_bytes: int) -> bool`
  - `resolve_video_offload(device: str, *, requested_video: bool, requested_state: bool, frame_count: int, image_size: int, free_vram_bytes: int | None) -> tuple[bool, bool]`
  - `SAM2VideoEngine.propagate` uses them. Policy: requests are only honored upward (the guard adds offload, never removes it). If video offload is already requested, the tensor stays on CPU and **nothing is escalated** — state offload is slower and unnecessary then. If video offload is NOT requested and the tensor lacks headroom, the guard enables **both** flags — the only configuration verified stable on the 11 GB card. There is deliberately no way to force offload OFF when the tensor does not fit — that configuration froze this machine.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_sam2_engine.py`: add `import pytest` to the imports, extend the `app.models.sam2_engine` import to also include `DeviceProfile`, `resolve_video_offload`, and `video_fits_in_vram`, then append:

```python
def test_full_video_tensor_fails_required_headroom() -> None:
    # 930 frames at 1024x1024 float32 is ~11,160 MiB: technically under an
    # 11,264 MiB card, but it leaves ~104 MiB — nowhere near enough for the
    # already-loaded model (~2,900 MiB baseline) plus headroom.
    assert not video_fits_in_vram(930, image_size=1024, free_bytes=11_264 * 1024**2)


def test_short_clip_video_tensor_fits_with_headroom() -> None:
    # 100 frames is ~1.2 GiB; fits an 8 GiB budget even with headroom.
    assert video_fits_in_vram(100, image_size=1024, free_bytes=8 * 1024**3)


def test_mps_always_offloads_video_and_state() -> None:
    assert resolve_video_offload(
        "mps",
        requested_video=False,
        requested_state=False,
        frame_count=10,
        image_size=1024,
        free_vram_bytes=None,
    ) == (True, True)


def test_cuda_offloads_when_video_tensor_lacks_headroom() -> None:
    assert resolve_video_offload(
        "cuda",
        requested_video=False,
        requested_state=False,
        frame_count=930,
        image_size=1024,
        free_vram_bytes=11_264 * 1024**2,
    ) == (True, True)


def test_cuda_keeps_gpu_video_when_tensor_fits() -> None:
    assert resolve_video_offload(
        "cuda",
        requested_video=False,
        requested_state=False,
        frame_count=100,
        image_size=1024,
        free_vram_bytes=8 * 1024**3,
    ) == (False, False)


def test_explicit_offload_requests_are_never_downgraded() -> None:
    assert resolve_video_offload(
        "cuda",
        requested_video=True,
        requested_state=True,
        frame_count=10,
        image_size=1024,
        free_vram_bytes=24 * 1024**3,
    ) == (True, True)


def test_explicit_video_offload_is_not_escalated_to_state_offload() -> None:
    # With the video already on CPU the giant tensor never reaches the GPU,
    # so a long clip must not drag state offload (slower) along with it.
    assert resolve_video_offload(
        "cuda",
        requested_video=True,
        requested_state=False,
        frame_count=930,
        image_size=1024,
        free_vram_bytes=11_264 * 1024**2,
    ) == (True, False)


def test_cpu_device_passes_requests_through() -> None:
    assert resolve_video_offload(
        "cpu",
        requested_video=False,
        requested_state=True,
        frame_count=930,
        image_size=1024,
        free_vram_bytes=None,
    ) == (False, True)


class _NullContext:
    def __enter__(self) -> "_NullContext":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class RecordingVideoPredictor:
    image_size = 1024

    def __init__(self) -> None:
        self.init_kwargs: dict[str, bool] | None = None

    def init_state(
        self,
        *,
        video_path: str,
        offload_video_to_cpu: bool,
        offload_state_to_cpu: bool,
    ) -> object:
        self.init_kwargs = {
            "offload_video_to_cpu": offload_video_to_cpu,
            "offload_state_to_cpu": offload_state_to_cpu,
        }
        return object()

    def add_new_points_or_box(self, **kwargs: object) -> None:
        return None

    def propagate_in_video(
        self, state: object, *, start_frame_idx: int, reverse: bool
    ) -> object:
        return iter(())


def fake_video_torch(free_bytes: int) -> SimpleNamespace:
    # Real torch cannot be used here: torch.autocast("cuda") and
    # torch.cuda.mem_get_info() are unavailable off-GPU.
    return SimpleNamespace(
        inference_mode=_NullContext,
        autocast=lambda **_kwargs: _NullContext(),
        float16="float16",
        cuda=SimpleNamespace(mem_get_info=lambda: (free_bytes, 11_264 * 1024**2)),
    )


def test_cuda_propagate_wires_offload_into_init_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Proof that the guard's decision actually reaches SAM2: a 930-frame
    # CUDA propagation on an 11 GiB budget must call init_state with both
    # offload flags enabled. This is the wiring the live GPU run relies on.
    frames = tmp_path / "frames"
    frames.mkdir()
    for index in range(930):
        (frames / f"{index:05d}.jpg").write_bytes(b"")

    engine = SAM2VideoEngine(tmp_path / "missing.pt", "cfg")
    predictor = RecordingVideoPredictor()
    engine._predictor = predictor
    engine._profile = DeviceProfile("cuda", "float16", "base-plus", (7, 5))
    monkeypatch.setattr(
        SAM2Engine,
        "_import_torch",
        staticmethod(lambda: fake_video_torch(11_264 * 1024**2)),
    )

    assert list(engine.propagate(frames, 0, (10, 10, 20, 20), reverse=False)) == []
    assert predictor.init_kwargs == {
        "offload_video_to_cpu": True,
        "offload_state_to_cpu": True,
    }
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
uv run --extra dev pytest tests/test_sam2_engine.py -q
```
Expected: FAIL with `ImportError: cannot import name 'resolve_video_offload'`.

- [ ] **Step 3: Implement the pure helpers**

In `backend/app/models/sam2_engine.py`, add `import logging` to the imports, then after the imports:

```python
logger = logging.getLogger(__name__)

# SAM2 keeps activations, the memory bank, and autocast copies alongside the
# stacked video tensor; require this much slack beyond the tensor itself.
_VIDEO_OFFLOAD_HEADROOM_BYTES = 3 * 1024**3


def video_fits_in_vram(frame_count: int, *, image_size: int, free_bytes: int) -> bool:
    """Whether SAM2's stacked float32 [N, 3, S, S] video tensor fits free VRAM
    with enough headroom left for the model and runtime allocations."""
    tensor_bytes = frame_count * 3 * image_size * image_size * 4
    return tensor_bytes + _VIDEO_OFFLOAD_HEADROOM_BYTES <= free_bytes


def resolve_video_offload(
    device: str,
    *,
    requested_video: bool,
    requested_state: bool,
    frame_count: int,
    image_size: int,
    free_vram_bytes: int | None,
) -> tuple[bool, bool]:
    """Final (offload_video, offload_state) flags for SAM2 init_state.

    MPS always offloads: its stacked video tensor exceeds MPSGraph's INT_MAX
    above ~750 frames. CUDA escalates only when the video would otherwise
    live on the GPU but lacks headroom (930 frames ~= 11,160 MiB against an
    11,264 MiB card plus a ~2,900 MiB loaded model froze an RTX 2080 Ti
    desktop via WDDM oversubscription). A tripped guard enables both flags —
    the only configuration verified stable on 11 GB. Requests are only
    honored upward; requested video offload already keeps the tensor on CPU,
    so nothing else is escalated.
    """
    if device == "mps":
        return True, True
    if (
        device == "cuda"
        and not requested_video
        and free_vram_bytes is not None
        and not video_fits_in_vram(
            frame_count, image_size=image_size, free_bytes=free_vram_bytes
        )
    ):
        logger.warning(
            "SAM2 video tensor for %d frames does not fit free VRAM (%d MiB); "
            "enabling CPU offload",
            frame_count,
            free_vram_bytes // (1024 * 1024),
        )
        return True, True
    return requested_video, requested_state
```

- [ ] **Step 4: Wire the guard into `propagate`**

In `SAM2VideoEngine.propagate`, replace this block:

```python
                # MPS cannot hold the stacked full-video tensor once it
                # exceeds INT_MAX elements (~750 frames at 1024x1024), so
                # frames must stay on CPU regardless of configuration.
                force_offload = profile.device == "mps"
                state = predictor.init_state(
                    video_path=str(frame_directory),
                    offload_video_to_cpu=self.offload_video_to_cpu or force_offload,
                    offload_state_to_cpu=self.offload_state_to_cpu or force_offload,
                )
```

with:

```python
                frame_count = sum(
                    1
                    for entry in Path(frame_directory).iterdir()
                    if entry.suffix.lower() in {".jpg", ".jpeg"}
                )
                free_vram_bytes = (
                    torch.cuda.mem_get_info()[0]
                    if profile.device == "cuda"
                    else None
                )
                offload_video, offload_state = resolve_video_offload(
                    profile.device,
                    requested_video=self.offload_video_to_cpu,
                    requested_state=self.offload_state_to_cpu,
                    frame_count=frame_count,
                    image_size=int(getattr(predictor, "image_size", 1024)),
                    free_vram_bytes=free_vram_bytes,
                )
                state = predictor.init_state(
                    video_path=str(frame_directory),
                    offload_video_to_cpu=offload_video,
                    offload_state_to_cpu=offload_state,
                )
```

Notes: `torch.cuda.mem_get_info()` returns `(free, total)` for the current device and is called after `_ensure_predictor`, so the model weights are already accounted for in `free`. The frame directory contains only the JPEG frame cache, so counting `.jpg`/`.jpeg` entries equals the frame count SAM2 will load.

- [ ] **Step 5: Run the weight-free suite (green)**

```powershell
uv run --extra dev pytest tests/test_sam2_engine.py -q
uv run --extra dev pytest -m "not integration" -q
```
Expected: new tests pass; whole weight-free suite 0 failed (Tasks 2–4 fixed the rest).

- [ ] **Step 6: Live verification on the real GPU — observation plus a kill switch**

This re-runs the exact scenario that previously froze the machine. **Job cancellation cannot save you**: the fatal allocation happens inside `init_state`, before the first tracked frame, and `/api/jobs/{id}/cancel` is only observed at per-frame progress reports. The wiring test in Step 1 is the actual proof the guard reaches `init_state`; this live run confirms it on real hardware. Monitoring is observation; the only effective emergency action is killing the backend process.

1. Ensure `SAM2_OFFLOAD_VIDEO_TO_CPU` and `SAM2_OFFLOAD_STATE_TO_CPU` are **unset** in the backend's environment.
2. From the repo root, start the backend with `powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1`, keeping its console visible for log output.
3. Record the backend's PID **before** starting any track:
   ```powershell
   Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -match 'uvicorn' } | Select-Object ProcessId, CommandLine
   ```
4. In a second console: `nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv -l 5` (observation only — a 5 s poll can miss a fast allocation; do not rely on it as protection).
5. Start a full track of the 930-frame video through the UI or API (`POST /api/track` with the existing video and a click selection; `GET /api/jobs` shows the job id).
6. **The warning must appear before frame loading starts.** The backend log must show `SAM2 video tensor for 930 frames does not fit free VRAM ... enabling CPU offload` *before* SAM2's `frame loading (JPEG)` progress output begins. If frame loading starts without the warning, immediately kill the backend:
   ```powershell
   Stop-Process -Id <recorded PID> -Force
   ```
   (During bring-up, Ctrl+C after a wedged allocation left an 11.6 GB python process alive — use `Stop-Process -Force`, and verify with `nvidia-smi` that the memory was released.)
7. Expected healthy run: peak `memory.used` in the ~4,000–5,000 MiB band, GPU utilization bursts to ~90%, job completes in roughly 3–4 minutes.
8. With the track complete, exercise the rest of the real flow on the new code: start an export of that track (UI or `POST /api/export`), then verify the output:
   ```powershell
   ffprobe -v error -show_entries stream=codec_name,width,height,nb_frames -of default=noprint_wrappers=1 ..\exports\<job_id>.mp4
   ```
   Expected: h264 video at the requested dimensions with 930 frames plus an audio stream; open the file and visually confirm the crop follows the tracked player.

- [ ] **Step 7: Commit**

```powershell
git add app/models/sam2_engine.py tests/test_sam2_engine.py
git commit -m "Auto-enable SAM2 CPU offload when the video tensor exceeds free VRAM"
```

---

### Task 6: Align every document with the Windows verification results

**Files:**
- Modify: `AGENTS.md` (repo root)
- Modify: `README.md` (repo root)
- Modify: `website/index.html`

Attribution note: the measured numbers below (launchers working, 3m13s track, 40 s export, 4,253 MiB peak, frame-650 identity switch reproduced) come from the recorded 2026-08-28 bring-up report on this machine, and the track/export/VRAM numbers are re-verified live by Task 5 Step 6 of this plan. `run.ps1` is exercised again in Task 5 Step 6; `dev.ps1` was verified at bring-up and is not re-run here.

- [ ] **Step 1: Update the AGENTS.md device matrix and config table**

Change the Turing row of the device matrix to:

```markdown
| CUDA Turing (target: RTX 2080 Ti, 11 GB) | base-plus, fp16, SDPA | flash-attn unsupported; CPU offload auto-engages when the stacked video tensor exceeds free VRAM |
```

And change the `SAM2_OFFLOAD_VIDEO_TO_CPU / SAM2_OFFLOAD_STATE_TO_CPU` row's meaning cell to:

```markdown
forced on automatically on MPS, and on CUDA when the stacked video tensor cannot fit free VRAM
```

- [ ] **Step 2: Add the AGENTS.md pitfall**

Under "Known pitfalls", after the MPS long-video bullet, add:

```markdown
- **CUDA VRAM freeze**: without CPU offload, SAM2 stacks the whole video as one float32
  tensor inside `init_state` (930 frames ≈ 11,160 MiB — nearly all of an 11,264 MiB
  card, leaving no room for the loaded model). Windows/WDDM then oversubscribes GPU
  memory, utilization drops to ~0%, and the desktop can freeze until reboot (observed
  on the RTX 2080 Ti, 2026-08-28). Job cancellation cannot interrupt the allocation —
  it happens before the first tracked frame. `resolve_video_offload` in
  `sam2_engine.py` now auto-enables offload when the tensor lacks headroom; don't
  bypass it. Measured with offload: peak ~4.3 GB VRAM, 930 frames in 3m13s (~4.8 fps),
  ~6× faster than MPS.
```

- [ ] **Step 3: Update the AGENTS.md status section**

In "Status and open work", replace:

```markdown
M0–M7 are complete and committed (git log is authoritative). Not yet done:

1. **Windows/RTX 2080 Ti verification** (code exists, hardware untested): `run.ps1` /
   `dev.ps1`, SAM 2 peak VRAM, and CUDA tracking speed.
2. **Multi-anchor track splicing** (proposed, top priority for contact sports): re-anchor
```

with:

```markdown
M0–M7 are complete and committed (git log is authoritative). Windows/RTX 2080 Ti was
verified 2026-08-28: `run.ps1`/`dev.ps1` work, full 930-frame track in 3m13s (~4.8 fps,
~6× Mac MPS), export in 40 s, peak ~4.3 GB VRAM with CPU offload (auto-engaged). The
frame-650 identity switch reproduces identically on CUDA. Not yet done:

1. **Multi-anchor track splicing** (proposed, top priority for contact sports): re-anchor
```

and renumber the remaining items (network-exposure hardening becomes 2, PyInstaller packaging becomes 3).

- [ ] **Step 4: Fix the README's Windows install, offload row, and limitations**

Three separate spots in `README.md`:

(a) In the Windows install block, the manual torch reinstall is now obsolete **and points at a stale index (cu121/torch 2.5.1)** — after Task 1 it would fight the lockfile. Replace:

```powershell
uv python install 3.12
uv sync --project backend --python 3.12 --extra dev

uv pip install --python backend\.venv\Scripts\python.exe --reinstall `
  torch==2.5.1 torchvision==0.20.1 `
  --index-url https://download.pytorch.org/whl/cu121

backend\.venv\Scripts\python.exe scripts\fetch_models.py
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1
```

with:

```powershell
uv python install 3.12
uv sync --project backend --python 3.12 --extra dev

backend\.venv\Scripts\python.exe scripts\fetch_models.py
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1
```

and add this sentence to the paragraph immediately after the block: `On Windows, uv installs CUDA (cu124) PyTorch wheels automatically; no manual torch install is needed.`

(b) In the environment-variable table, replace:

```markdown
| `SAM2_OFFLOAD_VIDEO_TO_CPU` / `SAM2_OFFLOAD_STATE_TO_CPU` | `0` | SAM 2 memory offload; forced on MPS. |
```

with:

```markdown
| `SAM2_OFFLOAD_VIDEO_TO_CPU` / `SAM2_OFFLOAD_STATE_TO_CPU` | `0` | SAM 2 memory offload; forced on MPS, auto-enabled on CUDA when the video tensor cannot fit free VRAM. |
```

(c) In "Known limitations", replace:

```markdown
- Full 930-frame tracking takes about 20 minutes on Apple Silicon. Use short ranges to iterate.
```

with:

```markdown
- Full 930-frame tracking takes about 20 minutes on Apple Silicon and about 3 minutes on an RTX 2080 Ti. Use short ranges to iterate.
```

and replace:

```markdown
- RTX 2080 Ti support exists in code, but SAM 2 speed and peak VRAM remain unverified on that hardware.
```

with:

```markdown
- Verified on RTX 2080 Ti (2026-08-28): 930-frame track in about 3 minutes (~4.8 fps) at ~4.3 GB peak VRAM with automatic CPU offload.
```

- [ ] **Step 5: Update the website hardware note**

In `website/index.html`, replace:

```html
<p class="hardware-note reveal">RTX 2080 Ti support is implemented but still awaiting real-hardware verification; PlayTrack does not claim a measured 11 GB VRAM ceiling yet.</p>
```

with:

```html
<p class="hardware-note reveal">Verified on an RTX 2080 Ti (11 GB): a full 930-frame track completes in about 3 minutes at a measured peak of ~4.3 GB VRAM with automatic CPU offload.</p>
```

Leave everything else on the page untouched (no analytics, no remote resources — repo rule). The live-site smoke test after Pages deploys is the Mac maintainer's job post-merge, not yours.

- [ ] **Step 6: Validate the website and commit**

```powershell
cd ..
node website\test-site.mjs
```
Expected: validator passes.

```powershell
git add AGENTS.md README.md website\index.html
git commit -m "Document Windows CUDA verification results"
cd backend
```

---

## Final verification and handoff

- [ ] **Full backend suite** (weights present on this machine; CUDA tests run):

```powershell
uv run --extra dev pytest -q
```
Expected: **0 failed**; 10 skipped (launcher tests); everything else passes, including both SAM2 integration tests.

- [ ] **Frontend and website gates** (required by AGENTS.md before claiming work done; node_modules already installed at bring-up):

```powershell
cd ..\frontend
npm test
npm run typecheck
npm run build
cd ..
node website\test-site.mjs
cd backend
```
Expected: all pass (frontend code is untouched by this plan; this proves it).

- [ ] **Fresh-environment proof** that Task 1 holds:

```powershell
uv sync --extra dev --reinstall-package torch --reinstall-package torchvision
uv run python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```
Expected: `2.6.0+cu124 True`.

- [ ] **Push the branch** (never main):

```powershell
git push -u origin fix/windows-cuda-and-portability
```

- [ ] **Report back** with: the exact final pytest summary line; the `uv.lock` torch/torchvision resolution for win32 and non-win32; the Task 5 Step 6 observations (warning appeared before frame loading? peak VRAM? wall-clock? kill switch used?); the export `ffprobe` output and visual check; the website validator result; and anything that deviated from this plan.
