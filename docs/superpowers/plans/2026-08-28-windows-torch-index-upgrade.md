# Windows Torch Index Upgrade Implementation Plan

> **For agentic workers:** Execute the tasks strictly in order, checking off each step. This is an EXPERIMENT with an explicit revert path: the outcome may legitimately be "reverted, not upgradable" — report honestly either way.

**Goal:** Move the Windows torch fork from `2.6.0+cu124` to `2.13.0+cu132` (parity with macOS) to clear the 8 open GitHub Dependabot advisories against `backend/uv.lock`, gated on driver compatibility and on the newer wheels still shipping sm_75 (Turing) kernels for the RTX 2080 Ti.

**Architecture:** One config change (the uv index name/URL in `backend/pyproject.toml` plus a re-lock), wrapped in hard gates in this order: preflight (clean tree, no running backend, driver version), a recorded baseline selection on the current environment, wheel discovery, lock inspection, an offline GPU canary that exercises SAM2's actual kernel paths (SDPA under Turing flags), then the standard suites and a real tracking run. Any gate failure means the **Revert procedure** below, verbatim — never improvisation.

**Tech Stack:** uv (lockfile-driven), PyTorch wheels from download.pytorch.org, pytest.

**Spec:** the **Background** section below — self-contained.

**Provenance:** adversarially reviewed by Codex on 2026-08-28 (1 blocker, 10 major findings); all incorporated. The cu132 wheel availability below was independently verified from macOS on 2026-08-28.

## Background

- `backend/pyproject.toml` pins a Windows-only uv source: index `pytorch-cu124` (`https://download.pytorch.org/whl/cu124`, `explicit = true`) for `torch` and `torchvision`, resolving `torch 2.6.0+cu124` / `torchvision 0.21.0+cu124` on win32. macOS/Linux resolve `torch 2.13.0` / `torchvision 0.28.0` from PyPI.
- The 8 open Dependabot alerts, all against the `2.6.0+cu124` lock entry — **every one exits its vulnerable range at torch 2.13.0**:

  | Alert | GHSA | Vulnerable range | Patched |
  |---|---|---|---|
  | #21 | GHSA-rrmf-rvhw-rf47 | <= 2.12.1 | 2.13.0 |
  | #20 | GHSA-qfhq-4f3w-5fph | < 2.10.0 | 2.10.0 |
  | #19 | GHSA-vgrw-7cvw-pwgx | < 2.9.1 | 2.9.1 |
  | #18 | GHSA-x3gm-94wq-g975 | <= 2.6.0 | — |
  | #17 | GHSA-f4hp-rmr7-r7v8 | <= 2.6.0 | — |
  | #16 | GHSA-c678-jfcj-6jmf | <= 2.6.0 | — |
  | #15 | GHSA-887c-mr87-cxwp | <= 2.7.1 | 2.8.0 |
  | #14 | GHSA-3749-ghw9-m3mg | < 2.7.1-rc1 | 2.7.1-rc1 |

  After the branch merges, report the actual remaining alert count rather than assuming — the Mac maintainer checks `gh api repos/pedrofuentes/playtrack/dependabot/alerts`.
- **Expected winner: `cu132`.** Verified live on 2026-08-28: `https://download.pytorch.org/whl/cu132/` serves `torch-2.13.0+cu132` and `torchvision-0.28.0+cu132` as BOTH `cp311` and `cp312` `win_amd64` wheels. The torch 2.13 release pairs CUDA 12.6 / 13.0 / 13.2 — there is no cu128/cu129 line for 2.13.
- **Driver requirement:** a CUDA 13.x wheel needs an NVIDIA driver of the 580 family or newer. Task 0 gates on this BEFORE any download — a too-old driver would fail only after installing a ~1.9 GB wheel. Do not update the GPU driver yourself; that is outside this plan's authorization — stop and report instead.
- The risk being tested: newer CUDA lines may drop sm_75 (Turing) kernels, or SDPA/conv kernels may misbehave on Turing even when a GEMM works. `2.6.0+cu124` is the proven configuration.
- The SAM2 VRAM guard (backend/app/models/sam2_engine.py) logs `SAM2 safety guard: ... MiB video tensor plus ... MiB headroom exceeds ... MiB free VRAM; enabling CPU offload`. **The guard is intentionally silent when `SAM2_OFFLOAD_VIDEO_TO_CPU=1` is already set** — the full-track test below requires both offload env vars UNSET, or the missing warning would falsely look like a failure. SAM2's fatal-if-unguarded allocation happens inside `init_state`, before the first tracked frame; job cancellation cannot interrupt it — only killing the backend process can.
- All PowerShell commands are Windows PowerShell 5.1-safe (no `&&`) and root-invariant: they use `$RepoRoot` and `--project`, so they work from any directory.

## Global Constraints

- First define, in every console you use:
  ```powershell
  $RepoRoot = (git rev-parse --show-toplevel).Trim()
  $Backend = Join-Path $RepoRoot 'backend'
  ```
- Branch first (after Task 0's preflight):
  ```powershell
  git -C $RepoRoot fetch origin
  git -C $RepoRoot switch -c fix/windows-torch-index-upgrade origin/main
  ```
  **Never commit to main; push the branch and stop** — the Mac maintainer re-runs the POSIX suite and merges.
- Never hand-edit `uv.lock`; only `uv lock` / `uv sync` touch it.
- Never commit `data/`, `exports/`, `checkpoints/`.
- Commit subjects: plain imperative.
- Do not kill any process you did not start for this plan; if a conflicting process exists, report it and ask for direction.

### Revert procedure (run verbatim at any failed gate, then skip to Report back)

```powershell
# 1. Stop the backend if THIS PLAN started one (recorded PID from Task 5).
# 2. Restore the two config files and prove the tree is clean:
git -C $RepoRoot restore -- backend/pyproject.toml backend/uv.lock
git -C $RepoRoot diff --exit-code -- backend/pyproject.toml backend/uv.lock
# 3. Exact sync, force-reinstalling the big binary packages (safe after an
#    interrupted large-wheel replacement):
uv sync --project $Backend --extra dev --locked --reinstall-package torch --reinstall-package torchvision
# 4. Prove the proven configuration is back:
uv run --project $Backend python -c "import torch, torchvision; print(torch.__version__, torchvision.__version__, torch.cuda.is_available(), torch.cuda.get_device_capability())"
```
Expected: `2.6.0+cu124 0.21.0+cu124 True (7, 5)`. Report which gate failed and the exact output.

---

### Task 0: Preflight

- [ ] **Step 1: Clean target files and no running backend**

```powershell
git -C $RepoRoot status --short
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -match 'uvicorn' } | Select-Object ProcessId, CommandLine
```
Gates: `backend/pyproject.toml` and `backend/uv.lock` must NOT appear as modified (a dirty file would be erased by the revert procedure — stop and report if dirty). Port 8000 must be free and no uvicorn must be running against this checkout; if one is, report it — do not kill it.

- [ ] **Step 2: Driver gate**

```powershell
nvidia-smi --query-gpu=name,driver_version --format=csv
```
Record the output. Gate: the driver must satisfy the CUDA 13.x requirement (580-family or newer). If it does not, STOP before any edit or download and report the version — choosing `cu126` instead (driver family 525+) is a fallback the Mac maintainer must approve first; do not decide it alone.

---

### Task 1: Record a baseline selection on the CURRENT environment

This is the reproducible acceptance anchor for Task 5 — capture it before anything changes.

- [ ] **Step 1**: Start the backend (`powershell -ExecutionPolicy Bypass -File (Join-Path $RepoRoot 'scripts\run.ps1')` in a second console), then run ONE click selection through the API on the 930-frame example video: record the exact `videoId`, `frameIdx`, `x`, `y` you used, and the returned `box` and `score`. Save the exact request JSON to reuse verbatim in Task 5.
- [ ] **Step 2**: Stop that backend (its own console, Ctrl+C; verify port 8000 is free again).

---

### Task 2: Confirm the wheel line (discovery)

- [ ] **Step 1: Probe the candidate indexes, newest first**

```powershell
foreach ($cu in @('cu132','cu130','cu126')) {
  try {
    $html = (Invoke-WebRequest -UseBasicParsing -ErrorAction Stop "https://download.pytorch.org/whl/$cu/torch/").Content
    $t311 = [bool]($html | Select-String "torch-2\.13\.0\+$cu-cp311-cp311-win_amd64\.whl")
    $t312 = [bool]($html | Select-String "torch-2\.13\.0\+$cu-cp312-cp312-win_amd64\.whl")
    $html = (Invoke-WebRequest -UseBasicParsing -ErrorAction Stop "https://download.pytorch.org/whl/$cu/torchvision/").Content
    $v311 = [bool]($html | Select-String "torchvision-0\.28\.0\+$cu-cp311-cp311-win_amd64\.whl")
    $v312 = [bool]($html | Select-String "torchvision-0\.28\.0\+$cu-cp312-cp312-win_amd64\.whl")
    Write-Host "$cu : torch cp311=$t311 cp312=$t312 ; torchvision cp311=$v311 cp312=$v312"
  } catch {
    Write-Host "$cu : index unavailable ($($_.Exception.Message))"
  }
}
```
The strict regex (exact version, exact `+cuNNN` tag, exact ABI) cannot match dev/nightly wheels. Gate: pick the newest index reporting True for ALL FOUR (the project supports Python 3.11 and 3.12; the lock records both ABIs). Expected: `cu132`. If an index is *unavailable*, that is a network failure to report, not "no wheel". Never mix torch and torchvision across indexes.

---

### Task 3: Re-point the uv index and re-lock

**Files:** `backend/pyproject.toml`, `backend/uv.lock` (via `uv lock` only)

- [ ] **Step 1: Edit `pyproject.toml`** — replace the index name and URL (three places; `<CU>` is the Task 2 winner, expected `cu132`):

```toml
[tool.uv.sources]
torch = [{ index = "pytorch-<CU>", marker = "sys_platform == 'win32'" }]
torchvision = [{ index = "pytorch-<CU>", marker = "sys_platform == 'win32'" }]

[[tool.uv.index]]
name = "pytorch-<CU>"
url = "https://download.pytorch.org/whl/<CU>"
explicit = true
```

- [ ] **Step 2: Re-lock and inspect the FULL diff**

```powershell
uv lock --project $Backend
git -C $RepoRoot diff -- backend/uv.lock
```
Read the whole diff, not a filtered slice. Gates:
- win32 torch/torchvision become `2.13.0+<CU>` / `0.28.0+<CU>` from the new index;
- **non-Windows selected versions and sources are unchanged** (marker rewrites on entries shared with non-Windows are allowed only when caused by merging/splitting a Windows dependency fork — review each);
- new or removed packages are acceptable only if reachable exclusively from the Windows torch/torchvision closure (e.g. the Windows `sympy` fork moving 1.13.1→1.14.0, or a new `triton-windows`-style dependency) — list every one in the report;
- no `cu124` remnant survives:
  ```powershell
  Select-String -Path (Join-Path $Backend 'uv.lock') -SimpleMatch 'cu124'
  uv lock --project $Backend --check
  ```
  Gate: the `Select-String` prints nothing; `--check` passes.

- [ ] **Step 3: Compare per-platform trees** (before/after — run the "before" on main if not captured):

```powershell
uv tree --project $Backend --locked --python-version 3.12 --python-platform windows
uv tree --project $Backend --locked --python-version 3.12 --python-platform macos
```
Gate: the macOS tree is identical to main's.

- [ ] **Step 4: Sync**

```powershell
uv sync --project $Backend --extra dev
```

---

### Task 4: Hardware gates — offline, BEFORE any tracking

- [ ] **Step 1: Write and run the canary** (exercises SAM2's actual kernel paths — SDPA under the Turing flag configuration — not just cuBLAS):

```powershell
@'
import torch
import torchvision

print("torch", torch.__version__, "cuda", torch.version.cuda)
print("torchvision", torchvision.__version__)
assert torch.cuda.is_available(), "CUDA unavailable"
print("device", torch.cuda.get_device_name(0))
cap = torch.cuda.get_device_capability()
print("capability", cap)
assert cap == (7, 5), f"expected Turing (7, 5), got {cap}"
archs = torch.cuda.get_arch_list()
print("arch list", archs)
assert "sm_75" in archs, "sm_75 kernels missing from this build"

# PlayTrack's Turing SDPA configuration (_configure_cuda_attention)
torch.backends.cuda.enable_flash_sdp(False)
torch.backends.cuda.enable_math_sdp(True)
torch.backends.cuda.enable_mem_efficient_sdp(True)

with torch.inference_mode():
    q = torch.randn(1, 8, 1024, 64, device="cuda", dtype=torch.float16)
    out = torch.nn.functional.scaled_dot_product_attention(q, q, q)
    torch.cuda.synchronize()
    print("sdpa ok", float(out.float().abs().sum()))
    a = torch.randn(512, 512, device="cuda", dtype=torch.float16)
    print("gemm ok", float((a @ a).float().abs().sum()))
'@ | Set-Content -Encoding utf8 (Join-Path $env:TEMP 'playtrack-canary.py')
uv run --project $Backend python (Join-Path $env:TEMP 'playtrack-canary.py')
```
Gate: every assert passes and both ops print finite numbers. `no kernel image is available` or any SDPA failure means sm_75 support is effectively absent — **Revert procedure**. Record the full output for the report.

---

### Task 5: Software verification

- [ ] **Step 1: Full backend suite** (weights present; CUDA integration tests run):

```powershell
uv run --project $Backend --extra dev pytest -q
```
Gate: **0 failed**, 10 skipped (launcher tests). Any torch-related failure: **Revert procedure** and report the exact failures — do not patch app code in this plan.

- [ ] **Step 2: Repeat the Task 1 baseline selection, verbatim**

Prove both offload variables are absent, then start the backend and note its PID:

```powershell
Remove-Item Env:SAM2_OFFLOAD_VIDEO_TO_CPU -ErrorAction SilentlyContinue
Remove-Item Env:SAM2_OFFLOAD_STATE_TO_CPU -ErrorAction SilentlyContinue
Get-ChildItem Env: | Where-Object Name -like 'SAM2*'
```
(The listing must print nothing.) Start `run.ps1` in a second console prepared the same way, then:
```powershell
Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -match 'uvicorn' } | Select-Object ProcessId, CommandLine
```
Send the exact Task 1 request. Gate: score within ±0.05 of the baseline and the returned box selects the same player (confirm visually). A larger drift is a Turing-kernel red flag: **Revert procedure**.

- [ ] **Step 3: Full 930-frame track, observed**

With both offload vars still unset (the guard is silent otherwise — see Background): start the track; watch the backend log for the `SAM2 safety guard: ... enabling CPU offload` line BEFORE SAM2's `frame loading (JPEG)` output; `nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv -l 5` is observation only. If frame loading starts without the warning: `Stop-Process -Id <recorded PID> -Force`, then confirm with `nvidia-smi` that GPU memory returned to baseline. Expected healthy: peak ~4–5.5 GB, ~3–4.5 minutes. Record wall-clock and peak VRAM.

- [ ] **Step 4: Export and inspect**

Export the completed track; then:
```powershell
ffprobe -v error -show_entries stream=codec_name,width,height,nb_frames -of default=noprint_wrappers=1 (Join-Path $RepoRoot 'exports\<job_id>.mp4')
```
Gate: h264 at the requested dimensions, 930 video frames, audio stream present; open it and visually confirm the crop follows the tracked player.

- [ ] **Step 5: Frontend and website gates** (AGENTS.md requires them before claiming done):

```powershell
Set-Location (Join-Path $RepoRoot 'frontend')
npm test
npm run typecheck
npm run build
npm run test:pwa
Set-Location $RepoRoot
node website\test-site.mjs
```
Gate: all pass.

---

### Task 6: Docs and handoff

- [ ] **Step 1**: In `README.md`, change `On Windows, uv installs CUDA (cu124) PyTorch wheels automatically` to name the new line, e.g. `(cu132)`.

- [ ] **Step 2: Commit and push** (root-invariant):

```powershell
git -C $RepoRoot add backend/pyproject.toml backend/uv.lock README.md
git -C $RepoRoot commit -m "Move Windows torch to <CU> wheels to clear advisories"
git -C $RepoRoot push -u origin fix/windows-torch-index-upgrade
git -C $RepoRoot status --short
```
Gate: the final status shows no unexpected modifications.

---

## Report back

Whether it SUCCEEDED (branch pushed) or REVERTED (which gate, exact output):
- driver version and GPU name (Task 0); baseline selection request + score/box (Task 1);
- the chosen index; resolved torch/torchvision for win32 and non-win32; every package added/removed in the lock and why it is Windows-closure-only; confirmation `cu124` no longer appears in `uv.lock`;
- the full canary output (versions, capability, arch list, SDPA/GEMM results);
- the final pytest summary line; the repeated selection's score/box delta; full-track wall-clock and peak VRAM; whether the guard line appeared before frame loading; whether a forced kill was used and whether VRAM was released;
- export `ffprobe` output and the visual check; frontend/PWA/website gate results;
- final `git status --short`; anything that deviated from this plan.

On a revert outcome, the Mac maintainer will dismiss the 8 alerts (table above) as tolerable risk — local-only torch APIs PlayTrack never calls — citing this plan. That is a valid, expected outcome, not a failure.
