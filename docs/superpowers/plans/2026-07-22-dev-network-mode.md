# PlayTrack Dev Network Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit `scripts/dev.sh --network` mode that exposes both FastAPI and Vite on a trusted LAN while preserving localhost-only defaults and the existing `PLAYTRACK_HOST` override.

**Architecture:** `scripts/dev.sh` owns argument parsing, one resolved bind host, informational private-IPv4 discovery, two child processes, and cleanup. The existing Vite proxy continues to reach FastAPI at `127.0.0.1:8000`; tests execute the real launcher with stub `uv`, `npm`, and `ipconfig` programs so no sockets or models are required.

**Tech Stack:** Bash 3.2-compatible shell, Python 3.12 subprocess-based pytest tests, uv/pytest, Vite development server, FastAPI/Uvicorn.

## Global Constraints

- `scripts/dev.sh` with no arguments remains localhost-only: FastAPI and Vite bind to `127.0.0.1`.
- `scripts/dev.sh --network` binds FastAPI and Vite to `0.0.0.0`.
- `scripts/dev.sh --help` exits zero without starting child processes; unknown arguments exit nonzero after printing usage to standard error.
- `--network` takes precedence over `PLAYTRACK_HOST`; without the flag, explicit `PLAYTRACK_HOST` remains supported and controls both bind hosts.
- Vite API and WebSocket proxy targets remain `127.0.0.1:8000`.
- LAN address discovery is informational only and must not require network access, DNS, or a new dependency.
- Network exposure must print a prominent warning that PlayTrack has no authentication and should be used only on a trusted local network.
- Preserve the launcher's two-child cleanup behavior and do not touch live `data/`.
- Do not change Windows launchers, backend security middleware, frontend production/PWA behavior, API contracts, or persisted data.

---

### Task 1: Add Tested Unix Launcher Network Mode

**Files:**
- Modify: `scripts/dev.sh`
- Modify: `backend/tests/test_windows_scripts.py`
- Create: `backend/tests/test_unix_dev_script.py`

**Interfaces:**
- Consumes: optional `PLAYTRACK_HOST`; command arguments `--network` and `--help`; existing `uv` and `npm` executables.
- Produces: one Bash launcher whose resolved bind host is passed to `uvicorn --host` and `vite --host`, plus informational local/LAN URLs and a no-authentication warning.

- [ ] **Step 1: Strengthen the launcher source contract first**

Replace `test_unix_dev_script_uses_playtrack_host_and_branding` in `backend/tests/test_windows_scripts.py` with:

```python
def test_unix_dev_script_supports_safe_network_mode() -> None:
    script = script_text("dev.sh")

    assert "PLAYTRACK_HOST" in script
    assert "FINDME_HOST" not in script
    assert '"--network"' in script
    assert '"--help"' in script
    assert "0.0.0.0" in script
    assert "127.0.0.1" in script
    assert 'uv run uvicorn app.main:app --reload --host "$bind_host" --port 8000' in script
    assert 'npm run dev -- --host "$bind_host" --port 5173' in script
    assert "no authentication" in script
    assert "trusted local network" in script
    assert "PlayTrack backend" in script
    assert "PlayTrack frontend" in script
```

- [ ] **Step 2: Add shell-level launcher tests before implementation**

Create `backend/tests/test_unix_dev_script.py`:

```python
from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEV_SCRIPT = REPO_ROOT / "scripts" / "dev.sh"


def executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def stubbed_launcher(
    tmp_path: Path,
    *arguments: str,
    host: str | None = None,
    lan_address: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    command_log = tmp_path / "commands.log"

    executable(
        bin_dir / "uv",
        """#!/bin/sh
printf 'uv %s\\n' "$*" >> "$PLAYTRACK_TEST_LOG"
/bin/sleep 0.1
""",
    )
    executable(
        bin_dir / "npm",
        """#!/bin/sh
printf 'npm %s\\n' "$*" >> "$PLAYTRACK_TEST_LOG"
trap 'printf "npm terminated\\n" >> "$PLAYTRACK_TEST_LOG"; exit 0' TERM INT
while :; do /bin/sleep 0.1; done
""",
    )
    executable(bin_dir / "sleep", "#!/bin/sh\n/bin/sleep 0.01\n")
    ipconfig_body = (
        f"""#!/bin/sh
if [ "$*" = "getifaddr en0" ]; then
  printf '%s\\n' '{lan_address}'
  exit 0
fi
exit 1
"""
        if lan_address is not None
        else "#!/bin/sh\nexit 1\n"
    )
    executable(bin_dir / "ipconfig", ipconfig_body)
    executable(bin_dir / "hostname", "#!/bin/sh\nexit 1\n")

    environment = os.environ.copy()
    environment["PATH"] = f"{bin_dir}{os.pathsep}{environment['PATH']}"
    environment["PLAYTRACK_TEST_LOG"] = str(command_log)
    if host is None:
        environment.pop("PLAYTRACK_HOST", None)
    else:
        environment["PLAYTRACK_HOST"] = host

    result = subprocess.run(
        ["/bin/bash", str(DEV_SCRIPT), *arguments],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    commands = command_log.read_text(encoding="utf-8") if command_log.exists() else ""
    return result, commands


def test_help_exits_without_starting_children(tmp_path: Path) -> None:
    result, commands = stubbed_launcher(tmp_path, "--help")

    assert result.returncode == 0
    assert "Usage: scripts/dev.sh [--network]" in result.stdout
    assert commands == ""


def test_unknown_argument_fails_without_starting_children(tmp_path: Path) -> None:
    result, commands = stubbed_launcher(tmp_path, "--public")

    assert result.returncode == 2
    assert "Unknown option: --public" in result.stderr
    assert "Usage: scripts/dev.sh [--network]" in result.stderr
    assert commands == ""


def test_multiple_arguments_fail_without_starting_children(tmp_path: Path) -> None:
    result, commands = stubbed_launcher(tmp_path, "--network", "--help")

    assert result.returncode == 2
    assert "Expected at most one option." in result.stderr
    assert "Usage: scripts/dev.sh [--network]" in result.stderr
    assert commands == ""


def test_default_mode_binds_both_children_to_localhost(tmp_path: Path) -> None:
    result, commands = stubbed_launcher(tmp_path)

    assert result.returncode == 1
    assert "uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000" in commands
    assert "npm run dev -- --host 127.0.0.1 --port 5173" in commands
    assert "PlayTrack backend: http://127.0.0.1:8000" in result.stdout
    assert "PlayTrack frontend: http://127.0.0.1:5173" in result.stdout
    assert "no authentication" not in result.stdout
    assert "npm terminated" in commands


def test_network_mode_binds_both_children_and_reports_lan_url(tmp_path: Path) -> None:
    result, commands = stubbed_launcher(
        tmp_path,
        "--network",
        host="127.0.0.1",
        lan_address="192.168.50.23",
    )

    assert result.returncode == 1
    assert "uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000" in commands
    assert "npm run dev -- --host 0.0.0.0 --port 5173" in commands
    assert "PlayTrack frontend (local): http://127.0.0.1:5173" in result.stdout
    assert "PlayTrack frontend (network): http://192.168.50.23:5173" in result.stdout
    assert "no authentication" in result.stdout
    assert "trusted local network" in result.stdout


def test_explicit_host_controls_both_children_and_warns_when_public(tmp_path: Path) -> None:
    result, commands = stubbed_launcher(tmp_path, host="0.0.0.0")

    assert result.returncode == 1
    assert "uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000" in commands
    assert "npm run dev -- --host 0.0.0.0 --port 5173" in commands
    assert "no authentication" in result.stdout


def test_network_mode_starts_when_lan_address_detection_fails(tmp_path: Path) -> None:
    result, commands = stubbed_launcher(tmp_path, "--network")

    assert result.returncode == 1
    assert "uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000" in commands
    assert "npm run dev -- --host 0.0.0.0 --port 5173" in commands
    assert "http://<this-machine-ip>:5173" in result.stdout
    assert "no authentication" in result.stdout
```

- [ ] **Step 3: Run the focused tests to verify RED**

Run:

```bash
cd backend
UV_CACHE_DIR=/private/tmp/playtrack-network-uv uv run --extra dev pytest \
  tests/test_windows_scripts.py::test_unix_dev_script_supports_safe_network_mode \
  tests/test_unix_dev_script.py -q
```

Expected: the source-contract test fails because `dev.sh` has no `--network` or explicit Vite host, and the shell-level tests fail because the current launcher treats `--help`/unknown arguments as normal startup and always binds Vite to localhost.

- [ ] **Step 4: Implement the launcher behavior**

Replace `scripts/dev.sh` with:

```bash
#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage: scripts/dev.sh [--network]

Start the PlayTrack FastAPI and Vite development servers.

Options:
  --network  Bind both servers to 0.0.0.0 for trusted-LAN access.
  --help     Show this help and exit.
EOF
}

bind_host="${PLAYTRACK_HOST:-127.0.0.1}"

if (( $# > 1 )); then
  printf 'Expected at most one option.\n' >&2
  usage >&2
  exit 2
fi

case "${1:-}" in
  "") ;;
  "--network") bind_host="0.0.0.0" ;;
  "--help") usage; exit 0 ;;
  *)
    printf 'Unknown option: %s\n' "$1" >&2
    usage >&2
    exit 2
    ;;
esac

network_mode=0
case "$bind_host" in
  "127.0.0.1"|"localhost"|"::1") ;;
  *) network_mode=1 ;;
esac

is_private_ipv4() {
  local address="$1"
  local second_octet
  case "$address" in
    10.*|192.168.*) return 0 ;;
    172.*)
      second_octet="${address#172.}"
      second_octet="${second_octet%%.*}"
      [[ "$second_octet" =~ ^[0-9]+$ ]] &&
        (( second_octet >= 16 && second_octet <= 31 ))
      ;;
    *) return 1 ;;
  esac
}

detect_lan_ip() {
  local candidate
  local interface

  if command -v ipconfig >/dev/null 2>&1; then
    for interface in en0 en1; do
      if candidate="$(ipconfig getifaddr "$interface" 2>/dev/null)" &&
        is_private_ipv4 "$candidate"; then
        printf '%s\n' "$candidate"
        return 0
      fi
    done
  fi

  if command -v hostname >/dev/null 2>&1; then
    while IFS= read -r candidate; do
      if is_private_ipv4 "$candidate"; then
        printf '%s\n' "$candidate"
        return 0
      fi
    done < <(hostname -I 2>/dev/null | tr ' ' '\n' || true)
  fi

  return 1
}

cleanup() {
  trap - EXIT INT TERM
  kill "${backend_pid:-}" "${frontend_pid:-}" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

(
  cd "$root_dir/backend"
  uv run uvicorn app.main:app --reload --host "$bind_host" --port 8000
) &
backend_pid=$!

(
  cd "$root_dir/frontend"
  npm run dev -- --host "$bind_host" --port 5173
) &
frontend_pid=$!

echo "PlayTrack backend: http://${bind_host}:8000"
if (( network_mode )); then
  echo "PlayTrack frontend (local): http://127.0.0.1:5173"
  if lan_ip="$(detect_lan_ip)"; then
    echo "PlayTrack frontend (network): http://${lan_ip}:5173"
  else
    echo "PlayTrack frontend (network): http://<this-machine-ip>:5173"
  fi
  echo "WARNING: Network mode has no authentication. Use only on a trusted local network."
else
  echo "PlayTrack frontend: http://${bind_host}:5173"
fi
echo "Press Ctrl+C to stop both servers."

while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do
  sleep 1
done

echo "One PlayTrack process stopped; shutting down the other."
cleanup
wait "$backend_pid" "$frontend_pid" 2>/dev/null || true
exit 1
```

- [ ] **Step 5: Validate Bash syntax**

Run:

```bash
/bin/bash -n scripts/dev.sh
```

Expected: exit 0 with no output.

- [ ] **Step 6: Run the focused tests to verify GREEN**

Run:

```bash
cd backend
UV_CACHE_DIR=/private/tmp/playtrack-network-uv uv run --extra dev pytest \
  tests/test_windows_scripts.py::test_unix_dev_script_supports_safe_network_mode \
  tests/test_unix_dev_script.py -q
```

Expected: `8 passed` with only the repository's pre-existing Starlette/httpx deprecation warning, if emitted.

- [ ] **Step 7: Run the backend weight-free suite**

Run:

```bash
cd backend
UV_CACHE_DIR=/private/tmp/playtrack-network-uv uv run --extra dev pytest -m "not integration"
```

Expected: all selected tests pass; integration tests remain deselected. A pre-existing Starlette/httpx deprecation warning may remain.

- [ ] **Step 8: Commit the tested launcher**

```bash
git add scripts/dev.sh backend/tests/test_windows_scripts.py backend/tests/test_unix_dev_script.py
git commit -m "Add trusted-LAN mode to dev launcher"
```

---

### Task 2: Document Network Mode and Verify the Repository

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`

**Interfaces:**
- Consumes: `scripts/dev.sh --network`, `scripts/dev.sh --help`, and backward-compatible `PLAYTRACK_HOST` behavior from Task 1.
- Produces: user and agent instructions that distinguish safe localhost development from explicit unauthenticated LAN exposure.

- [ ] **Step 1: Add failing documentation assertions**

Append this test to `backend/tests/test_windows_scripts.py`:

```python
def test_docs_explain_unix_network_mode_and_warning() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    for document in (readme, agents):
        assert "scripts/dev.sh --network" in document
        assert "127.0.0.1" in document
        assert "0.0.0.0" in document
        assert "5173" in document
        assert "8000" in document
        assert "no authentication" in document
        assert "trusted local network" in document

    assert "preferred development interface" in readme
    assert "PLAYTRACK_HOST" in readme
    assert "PLAYTRACK_HOST" in agents
```

- [ ] **Step 2: Run the documentation test to verify RED**

Run:

```bash
cd backend
UV_CACHE_DIR=/private/tmp/playtrack-network-uv uv run --extra dev pytest \
  tests/test_windows_scripts.py::test_docs_explain_unix_network_mode_and_warning -q
```

Expected: FAIL because neither document contains `scripts/dev.sh --network` or the complete trusted-network warning.

- [ ] **Step 3: Update the README macOS launch instructions**

In `README.md`, keep the existing local command and replace the single `Open <http://127.0.0.1:5173>.` line with:

````markdown
Open <http://127.0.0.1:5173> on the PlayTrack computer.

To use the development UI from another device on the same trusted local network:

```bash
./scripts/dev.sh --network
```

This binds FastAPI to `0.0.0.0:8000` and Vite to `0.0.0.0:5173`. Open the
network URL printed by the launcher. Network mode has no authentication; never expose
these ports to the internet or an untrusted network.
````

Replace the `PLAYTRACK_HOST` configuration-table purpose with:

```markdown
| `PLAYTRACK_HOST` | `127.0.0.1` | Backward-compatible launcher bind override; `scripts/dev.sh --network` is the preferred development interface for explicit `0.0.0.0` LAN binding without authentication. |
```

- [ ] **Step 4: Update the agent guide**

In the `AGENTS.md` command block, replace the Unix launcher line with:

```text
scripts/dev.sh            # Mac dev, localhost: uvicorn --reload :8000 + Vite :5173
scripts/dev.sh --network  # Explicit trusted-LAN mode: binds both to 0.0.0.0 (no authentication)
```

After that command block, add:

````markdown
`scripts/dev.sh` is localhost-only by default. `scripts/dev.sh --network` exposes both
development ports and prints the LAN frontend URL; use it only on a trusted local network
because PlayTrack has no authentication. `PLAYTRACK_HOST` remains a backward-compatible
bind override, but `--network` is the preferred development interface.
````

Replace the `PLAYTRACK_HOST` configuration-table meaning with:

```markdown
| `PLAYTRACK_HOST` | `127.0.0.1` | backward-compatible launcher bind override; `scripts/dev.sh --network` is preferred for explicit `0.0.0.0` LAN binding (origin/host checks, but no authentication) |
```

- [ ] **Step 5: Run the focused documentation test to verify GREEN**

Run:

```bash
cd backend
UV_CACHE_DIR=/private/tmp/playtrack-network-uv uv run --extra dev pytest \
  tests/test_windows_scripts.py::test_docs_explain_unix_network_mode_and_warning -q
```

Expected: `1 passed`.

- [ ] **Step 6: Run all repository gates**

Run:

```bash
cd backend
UV_CACHE_DIR=/private/tmp/playtrack-network-uv uv run --extra dev pytest -m "not integration"

cd ../frontend
npm test -- --run
npm run typecheck
npm run build
npm run test:pwa

cd ..
node website/test-site.mjs
/bin/bash -n scripts/dev.sh
git diff --check
```

Expected: backend and frontend suites pass, typecheck/build/PWA pass, the website validator passes, Bash syntax is valid, and `git diff --check` prints nothing.

- [ ] **Step 7: Exercise launcher modes without opening sockets**

Run the shell-level tests verbosely:

```bash
cd backend
UV_CACHE_DIR=/private/tmp/playtrack-network-uv uv run --extra dev pytest \
  tests/test_unix_dev_script.py -vv
```

Expected: all seven launcher behavior tests pass. Confirm the output covers local binding, network binding, `--network` precedence, explicit `PLAYTRACK_HOST`, LAN URL discovery/fallback, usage, warnings, and no-child help/error paths.

- [ ] **Step 8: Perform a safe live smoke test when the standard ports are free**

First check without stopping existing processes:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
lsof -nP -iTCP:5173 -sTCP:LISTEN
```

If both commands report no listeners, run `scripts/dev.sh --network`, verify its warning and printed LAN URL, and from another terminal run:

```bash
curl -fsSI http://127.0.0.1:5173/
curl -fsS http://127.0.0.1:5173/api/library
```

Expected: the frontend returns HTTP 200 and the Vite proxy returns the library JSON. Stop only the launcher process started for this smoke test. If either standard port was already occupied, do not stop or replace the user's server; report the collision and use the passing stub integration tests as the launcher evidence.

- [ ] **Step 9: Commit documentation and its regression test**

```bash
git add README.md AGENTS.md backend/tests/test_windows_scripts.py
git commit -m "Document dev network mode"
```
