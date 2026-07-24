from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def script_text(name: str) -> str:
    return (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")


def test_run_script_checks_tools_builds_stale_frontend_and_opens_browser() -> None:
    script = script_text("run.ps1")

    assert "$ErrorActionPreference = 'Stop'" in script
    assert "Get-Command" in script
    assert "-Name 'npm.cmd'" in script
    assert "https://docs.astral.sh/uv/getting-started/installation/" in script
    assert "https://nodejs.org/en/download" in script
    assert "--version" in script
    assert "Backend environment is missing" in script
    assert "Test-FrontendBuildStale" in script
    assert all(token in script for token in ("npm", "run", "build"))
    assert "uvicorn" in script
    assert "-ArgumentList @('run', '--no-sync', 'uvicorn'" in script
    assert "'--no-sync'" in script
    assert "127.0.0.1" in script
    assert "Start-Process $AppUrl" in script
    assert "PLAYTRACK_HOST" in script
    assert "FINDME_HOST" not in script
    assert "PlayTrack" in script


def test_dev_script_starts_reload_backend_and_vite_and_cleans_up() -> None:
    script = script_text("dev.ps1")

    assert "$ErrorActionPreference = 'Stop'" in script
    assert "Get-Command" in script
    assert "-Name 'npm.cmd'" in script
    assert "--version" in script
    assert "Backend environment is missing" in script
    assert "uvicorn" in script and "--reload" in script
    assert "-ArgumentList @('run', '--no-sync', '--extra', 'dev', 'uvicorn'" in script
    assert "'--no-sync'" in script
    assert all(token in script for token in ("npm", "run", "dev"))
    assert "5173" in script and "8000" in script
    assert "Stop-ProcessTree" in script
    assert "finally" in script
    assert "PlayTrack" in script


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
