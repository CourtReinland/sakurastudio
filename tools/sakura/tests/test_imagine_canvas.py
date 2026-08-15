"""Focused tests for Imagine Canvas, mood boards, and shared style lock."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from sakura.moodboards import (
    list_moodboard_images,
    list_recent_studio_assets,
    resolve_moodboard_file,
)
from sakura.studio_app import app
from sakura.studio_style import inject_style_reference, load_studio_style

# 1×1 PNG
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x00\x03\x00\x01\x00\x05\xfe\xd4+\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_canvas_tab_in_studio_html() -> None:
    from sakura import studio_app

    html = studio_app.STUDIO_HTML
    assert 'data-tab="canvas"' in html
    assert 'id="panel-canvas"' in html
    assert 'id="canvasPins"' in html
    assert 'id="btnCanvasGen"' in html
    assert 'id="btnCanvasIterate"' in html
    assert "/api/moodboards" in html
    assert "/api/imagine" in html
    assert 'data-tab="swaps"' in html
    assert 'data-tab="flow"' in html


def test_moodboard_list_and_safe_resolve(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    board = tmp_path / "moodboards" / "gemini"
    board.mkdir(parents=True)
    img = board / "suki_ref.png"
    img.write_bytes(_PNG)
    (tmp_path / "moodboards" / "notes.txt").write_text("ignore", encoding="utf-8")

    items = list_moodboard_images(catalog)
    assert len(items) == 1
    assert items[0]["path"] == "gemini/suki_ref.png"
    assert items[0]["folder"] == "gemini"

    resolved = resolve_moodboard_file(catalog, "gemini/suki_ref.png")
    assert resolved == img.resolve()

    try:
        resolve_moodboard_file(catalog, "../secrets.png")
        raise AssertionError("traversal should fail")
    except ValueError:
        pass


def test_moodboard_api_lists_and_serves(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    img = tmp_path / "moodboards" / "pixiv" / "lantern.png"
    img.parent.mkdir(parents=True)
    img.write_bytes(_PNG)

    client = TestClient(app)
    listed = client.get("/api/moodboards", params={"catalog": str(catalog)})
    assert listed.status_code == 200
    data = listed.json()
    assert data["ok"] is True
    assert data["count"] == 1
    assert data["items"][0]["path"] == "pixiv/lantern.png"

    served = client.get(
        "/api/moodboard-file",
        params={"catalog": str(catalog), "path": "pixiv/lantern.png"},
    )
    assert served.status_code == 200
    assert served.content == _PNG

    bad = client.get(
        "/api/moodboard-file",
        params={"catalog": str(catalog), "path": "../../etc/passwd"},
    )
    assert bad.status_code == 400


def test_studio_style_get_shared_lock(catalog_root: Path) -> None:
    style = load_studio_style(catalog_root, "title.sakura_tea_house")
    assert style["title_id"] == "title.sakura_tea_house"
    assert "enabled" in style
    assert style["path"] and style["path"].endswith("studio.yaml")

    client = TestClient(app)
    r = client.get(
        "/api/studio-style",
        params={"title": "title.sakura_tea_house", "catalog": str(catalog_root)},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["style"]["title_id"] == "title.sakura_tea_house"


def test_inject_style_reference_replaces_last_when_full() -> None:
    refs = [
        {"kind": "asset", "asset_id": "asset.one"},
        {"kind": "asset", "asset_id": "asset.two"},
        {"kind": "asset", "asset_id": "asset.three"},
    ]
    out, injected = inject_style_reference(
        refs,
        {"enabled": True, "asset_id": "asset.style.lock", "active": True},
    )
    assert injected is True
    assert len(out) == 3
    assert out[-1]["asset_id"] == "asset.style.lock"
    assert out[0]["asset_id"] == "asset.one"


def test_studio_recent_lists_studio_assets(catalog_root: Path) -> None:
    items = list_recent_studio_assets(catalog_root, limit=8)
    assert isinstance(items, list)
    client = TestClient(app)
    r = client.get("/api/studio-recent", params={"catalog": str(catalog_root), "limit": 8})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "items" in data


def test_imagine_moodboard_ref_requires_path(catalog_root: Path) -> None:
    client = TestClient(app)
    r = client.post(
        "/api/imagine",
        params={"catalog": str(catalog_root)},
        json={
            "prompt": "dusk tea house",
            "mode": "edit",
            "title_id": "title.sakura_tea_house",
            "bind": False,
            "use_style_board": False,
            "references": [{"kind": "moodboard"}],
        },
    )
    assert r.status_code == 400
