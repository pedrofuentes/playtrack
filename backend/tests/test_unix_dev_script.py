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
printf 'uv %s\n' "$*" >> "$PLAYTRACK_TEST_LOG"
attempts=0
while [ ! -f "$PLAYTRACK_TEST_READY" ] && [ "$attempts" -lt 100 ]; do
  /bin/sleep 0.01
  attempts=$((attempts + 1))
done
""",
    )
    executable(
        bin_dir / "npm",
        """#!/bin/sh
printf 'npm %s\n' "$*" >> "$PLAYTRACK_TEST_LOG"
: > "$PLAYTRACK_TEST_READY"
trap 'printf "npm terminated\n" >> "$PLAYTRACK_TEST_LOG"; exit 0' TERM INT
while :; do /bin/sleep 0.1; done
""",
    )
    executable(bin_dir / "sleep", "#!/bin/sh\n/bin/sleep 0.01\n")
    ipconfig_body = (
        f"""#!/bin/sh
if [ "$*" = "getifaddr en0" ]; then
  printf '%s\n' '{lan_address}'
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
    environment["PLAYTRACK_TEST_READY"] = str(tmp_path / "npm.ready")
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
