"""Pytest fixtures for sakura smoke tests."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOG = REPO_ROOT / "catalog"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def catalog_root() -> Path:
    assert CATALOG.is_dir(), f"catalog missing at {CATALOG}"
    return CATALOG
