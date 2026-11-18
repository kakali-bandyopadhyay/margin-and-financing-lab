"""Shared plumbing fixtures only (paths). Test logic lives in the test files."""
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def data_raw(repo_root: Path) -> Path:
    return repo_root / "data" / "raw"
