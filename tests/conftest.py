from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    assert (FIXTURES / "manifest.json").exists(), "run python tools/make_fixtures.py first"
    return FIXTURES


@pytest.fixture(scope="session")
def manifest(fixtures_dir) -> dict:
    return json.loads((fixtures_dir / "manifest.json").read_text(encoding="utf-8"))


def fixture_bytes(fid: str) -> bytes:
    return (FIXTURES / f"{fid}.txt").read_bytes()
