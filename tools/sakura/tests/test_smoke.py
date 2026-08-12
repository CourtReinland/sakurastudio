"""Fast, deterministic smoke tests — no API keys, no display, no game clones."""

from __future__ import annotations

from pathlib import Path

import pytest

from sakura import __version__
from sakura.bind import bind_list, bind_set
from sakura.cli import main as cli_main
from sakura.export_game import resolve_game_root
from sakura.import_unity import _resolve_unity_root, import_title
from sakura.loader import load_catalog
from sakura.validate import run_validate


LIVE_TITLES = (
    "title.sakura_match",
    "title.sakura_tea_house",
    "title.midnight_par",
)


def test_package_version_is_flow_workstation() -> None:
    assert __version__ == "0.9.1"


def test_cli_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli_main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "0.9.1" in out


def test_validate_catalog_loads(catalog_root: Path) -> None:
    root, findings = run_validate(catalog=catalog_root, include_examples=False)
    assert root == catalog_root.resolve()
    # Schema/load must succeed; findings may include warnings (missing binaries, etc.)
    assert isinstance(findings, list)
    # No machine-local absolute home paths should appear in messages
    joined = " ".join(f.message for f in findings)
    assert "/Users/capricorn" not in joined


def test_validate_examples(catalog_root: Path) -> None:
    root, findings = run_validate(catalog=catalog_root, include_examples=True)
    assert root.is_dir()
    assert isinstance(findings, list)


@pytest.mark.parametrize("title_id", LIVE_TITLES)
def test_validate_live_title(catalog_root: Path, title_id: str) -> None:
    root, findings = run_validate(catalog=catalog_root, title=title_id)
    assert root.is_dir()
    assert isinstance(findings, list)


def test_cli_validate_exit_codes(catalog_root: Path) -> None:
    # Live catalog should schema-validate with no errors (warnings OK → still exit 0).
    code = cli_main(["validate", "--catalog", str(catalog_root), "--examples"])
    assert code == 0


def test_bind_list_sakura_match(catalog_root: Path) -> None:
    ok, text = bind_list(catalog=catalog_root, title="title.sakura_match")
    assert ok is True
    assert "title.sakura_match" in text
    assert "slot.tile.red" in text


def test_bind_set_dry_run_does_not_write(catalog_root: Path) -> None:
    binds_path = catalog_root / "titles" / "sakura-match" / "bindings.yaml"
    before = binds_path.read_text(encoding="utf-8")
    result = bind_set(
        catalog=catalog_root,
        title="title.sakura_match",
        slot_id="slot.tile.red",
        asset_id="asset.tile_red_pastel_v1",
        dry_run=True,
        no_validate=True,
    )
    after = binds_path.read_text(encoding="utf-8")
    assert before == after
    assert result.ok is True
    assert "DRY-RUN" in result.message


def test_export_game_root_requires_env_or_arg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAKURA_GAME_ROOT", raising=False)
    monkeypatch.delenv("NIGHTMARE_GOLF_ROOT", raising=False)
    with pytest.raises(FileNotFoundError, match="SAKURA_GAME_ROOT"):
        resolve_game_root("title.midnight_par")
    # explicit path still works even if missing on disk (resolve only)
    p = resolve_game_root("title.midnight_par", "/tmp/sakura-fake-game-root")
    assert p == Path("/tmp/sakura-fake-game-root").resolve()


def test_no_hardcoded_capricorn_defaults() -> None:
    export_src = Path(__file__).resolve().parents[1] / "src" / "sakura" / "export_game.py"
    text = export_src.read_text(encoding="utf-8")
    assert "/Users/capricorn" not in text


def test_import_missing_unity_gives_portable_error(
    catalog_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SAKURA_UNITY_ROOT", raising=False)
    result = import_title(
        catalog=catalog_root,
        title="title.sakura_match",
        dry_run=True,
        generate_missing=False,
    )
    assert result.ok is False
    assert "Unity project not found" in result.message or "not a Unity project" in result.message.lower()
    assert "/Users/capricorn" not in result.message
    assert "SAKURA_UNITY_ROOT" in result.message or "--unity-root" in result.message


def test_import_respects_unity_root_env(
    catalog_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unity = tmp_path / "FakeUnity"
    (unity / "Assets").mkdir(parents=True)
    monkeypatch.setenv("SAKURA_UNITY_ROOT", str(unity))
    index = load_catalog(catalog_root, include_examples=False)
    resolved = _resolve_unity_root(index, "title.sakura_match")
    assert resolved == unity.resolve()


def test_studio_health_version(catalog_root: Path) -> None:
    from fastapi.testclient import TestClient

    from sakura.studio_app import app

    client = TestClient(app)
    r = client.get("/api/health", params={"catalog": str(catalog_root)})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["version"] == "0.9.1"
    # keys present; values may be false without secrets
    assert "xai_configured" in data
    assert "elevenlabs_configured" in data


def test_story_panel_removed_from_studio_html() -> None:
    from sakura import studio_app

    html = studio_app.STUDIO_HTML
    assert 'id="panel-story"' not in html
    assert "loadStory" not in html
    assert 'data-tab="story"' not in html
    assert "data-tab=\"flow\"" in html or 'data-tab="flow"' in html
