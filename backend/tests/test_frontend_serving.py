from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.videos import VideoStore


def make_frontend_dist(tmp_path: Path) -> Path:
    frontend_dist = tmp_path / "frontend" / "dist"
    assets = frontend_dist / "assets"
    assets.mkdir(parents=True)
    (frontend_dist / "index.html").write_text(
        "<!doctype html><title>FindMe SPA</title>", encoding="utf-8"
    )
    (assets / "app.js").write_text("console.log('FindMe')", encoding="utf-8")
    return frontend_dist


def test_built_frontend_serves_assets_and_spa_deep_links(tmp_path: Path) -> None:
    frontend_dist = make_frontend_dist(tmp_path)
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")

    with TestClient(create_app(store, frontend_dist=frontend_dist)) as client:
        root = client.get("/")
        asset = client.get("/assets/app.js")
        deep_link = client.get("/tracks/example")

    assert root.status_code == 200
    assert "FindMe SPA" in root.text
    assert asset.status_code == 200
    assert asset.text == "console.log('FindMe')"
    assert deep_link.status_code == 200
    assert deep_link.text == root.text


def test_api_routes_take_precedence_and_missing_assets_do_not_fall_back(
    tmp_path: Path,
) -> None:
    frontend_dist = make_frontend_dist(tmp_path)
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")

    with TestClient(create_app(store, frontend_dist=frontend_dist)) as client:
        health = client.get("/api/health")
        missing_api = client.get("/api/not-a-route")
        missing_asset = client.get("/assets/missing.js")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert missing_api.status_code == 404
    assert missing_asset.status_code == 404
