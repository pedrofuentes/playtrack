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
    assert "windows-tools.ps1" in script
    assert "Set-PlayTrackVideoToolEnvironment" in script
    assert script.index("Set-PlayTrackVideoToolEnvironment") < script.index(
        "Starting PlayTrack"
    )


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
    assert "windows-tools.ps1" in script
    assert "Set-PlayTrackVideoToolEnvironment" in script
    assert script.index("Set-PlayTrackVideoToolEnvironment") < script.index(
        "Starting the PlayTrack backend"
    )


def test_windows_setup_bootstraps_project_and_pinned_ffmpeg() -> None:
    setup = script_text("setup.ps1")

    assert "$ErrorActionPreference = 'Stop'" in setup
    assert "windows-tools.ps1" in setup
    assert "Install-PlayTrackFfmpeg" in setup
    assert all(token in setup for token in ("uv", "python", "install", "3.12"))
    assert all(token in setup for token in ("uv", "sync", "--project", "backend"))
    assert all(token in setup for token in ("npm", "ci"))
    assert "fetch_models.py" in setup
    assert "PlayTrack setup is complete" in setup


def test_windows_video_tool_helper_preserves_overrides_and_local_fallback() -> None:
    helper = script_text("windows-tools.ps1")

    assert "PLAYTRACK_FFMPEG" in helper
    assert "PLAYTRACK_FFPROBE" in helper
    assert ".tools\\ffmpeg" in helper
    assert "ffmpeg-9.0.1-essentials_build.zip" in helper
    assert (
        "FEC81AE03971D9DD4BE3EBE02E263BD2EC1D789483F931BDBA5F5715E65DA2E9"
        in helper
    )
    assert "Get-FileHash" in helper
    assert "Expand-Archive" in helper
    assert "Set-PlayTrackVideoToolEnvironment" in helper


def test_docs_make_setup_the_windows_entrypoint() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    windows_quick_start = readme.split("### Windows + NVIDIA CUDA", 1)[1].split(
        "### macOS + Apple Silicon", 1
    )[0]

    for document in (readme, agents):
        assert "scripts/setup.ps1" in document.replace("\\", "/")
        assert ".tools/ffmpeg" in document
    assert "ffmpeg` and `ffprobe` on `PATH`" not in windows_quick_start
    assert "scripts\\setup.ps1" in windows_quick_start


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
