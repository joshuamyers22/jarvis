from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def local_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point every test at a local directory instead of GCS.

    This is the payoff for routing all IO through fsspec: the storage layer is
    testable without a network, a bucket, or credentials.
    """
    monkeypatch.setenv("RP_LOCAL_ROOT", str(tmp_path))
    monkeypatch.setenv("RP_ENV", "dev")
    monkeypatch.delenv("RP_STORAGE_URI", raising=False)
    monkeypatch.delenv("RP_CLOUD", raising=False)

    from jobs.common.config import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()
