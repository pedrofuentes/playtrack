from __future__ import annotations

from pathlib import Path
import re

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import create_app
from app.videos import VideoStore


def make_client(
    tmp_path: Path, *, allowed_hosts: tuple[str, ...] = ()
) -> TestClient:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    return TestClient(create_app(store, allowed_hosts=allowed_hosts))


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://attacker.example"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_rejects_cross_site_browser_requests(
    tmp_path: Path, headers: dict[str, str]
) -> None:
    with make_client(tmp_path) as client:
        response = client.get("/api/health", headers=headers)

    assert response.status_code == 403
    assert response.json() == {"detail": "Cross-site requests are not allowed"}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "http://testserver"},
        {"Origin": "http://localhost:5173"},
        {"Origin": "http://127.0.0.1:5173"},
        {"Sec-Fetch-Site": "same-origin"},
    ],
)
def test_allows_cli_same_origin_and_vite_requests(
    tmp_path: Path, headers: dict[str, str]
) -> None:
    with make_client(tmp_path) as client:
        response = client.get("/api/health", headers=headers)

    assert response.status_code == 200


@pytest.mark.parametrize(
    "host",
    [
        "localhost:8000",
        "127.0.0.1:8000",
        "[::1]:8000",
        "192.168.1.20:8000",
        "10.0.10.10:8000",
        "172.16.1.4:8000",
        "testserver",
    ],
)
def test_allows_loopback_private_and_test_hosts(tmp_path: Path, host: str) -> None:
    with make_client(tmp_path) as client:
        response = client.get("/api/health", headers={"Host": host})

    assert response.status_code == 200


def test_allows_explicit_dns_host(tmp_path: Path) -> None:
    with make_client(tmp_path, allowed_hosts=("findme.lan",)) as client:
        response = client.get("/api/health", headers={"Host": "findme.lan:8000"})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "host",
    ["attacker.example", "findme.lan.attacker.example", "8.8.8.8", "bad host"],
)
def test_rejects_public_or_malformed_hosts(tmp_path: Path, host: str) -> None:
    with make_client(tmp_path) as client:
        response = client.get("/api/health", headers={"Host": host})

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid Host header"}


def test_rejects_foreign_websocket_origin(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        with pytest.raises(WebSocketDisconnect) as raised:
            with client.websocket_connect(
                "/ws/jobs/missing",
                headers={"Origin": "https://attacker.example"},
            ):
                pass

    assert raised.value.code == 4403


def test_every_http_response_has_server_generated_request_id(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.get(
            "/api/not-found", headers={"X-Request-ID": "attacker-controlled"}
        )

    request_id = response.headers["X-Request-ID"]
    assert response.status_code == 404
    assert request_id != "attacker-controlled"
    assert re.fullmatch(r"[0-9a-f]{32}", request_id)


def test_unexpected_errors_are_correlated_without_disclosing_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")

    def fail_get(_video_id: str) -> object:
        raise RuntimeError("secret path /private/source.mp4")

    monkeypatch.setattr(store, "get", fail_get)
    with TestClient(create_app(store), raise_server_exceptions=False) as client:
        response = client.get("/api/videos/video-1/file")

    payload = response.json()
    assert response.status_code == 500
    assert payload == {
        "detail": "Internal server error",
        "code": "internal_error",
        "errorId": response.headers["X-Request-ID"],
    }
    assert "secret path" not in response.text
    assert payload["errorId"] in caplog.text
    assert "secret path /private/source.mp4" in caplog.text
