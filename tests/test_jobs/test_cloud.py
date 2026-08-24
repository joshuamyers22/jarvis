"""Provider resolution.

Cheap tests around the one piece of logic that decides everything else.
"""

from __future__ import annotations

import pytest

from jobs.common.cloud import (
    LOG_CONN_ID,
    SECRETS_BACKEND,
    Cloud,
    infer_cloud,
    validate,
)


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("gs://bucket", Cloud.GCP),
        ("gs://bucket/nested/prefix", Cloud.GCP),
        ("s3://bucket", Cloud.AWS),
        ("s3a://bucket", Cloud.AWS),
        ("abfs://container@acct.dfs.core.windows.net", Cloud.AZURE),
        ("abfss://container@acct.dfs.core.windows.net", Cloud.AZURE),
        ("az://container", Cloud.AZURE),
        ("/tmp/data", Cloud.LOCAL),
        ("file:///tmp/data", Cloud.LOCAL),
    ],
)
def test_cloud_is_inferred_from_the_storage_uri(uri: str, expected: Cloud):
    assert infer_cloud(uri) == expected


def test_explicit_cloud_that_contradicts_the_uri_is_rejected():
    """The mismatch this guard exists to catch: RP_CLOUD=aws, gs:// bucket."""
    with pytest.raises(ValueError, match="does not start with"):
        validate(Cloud.AWS, "gs://bucket")


@pytest.mark.parametrize("uri", ["", "relative/path", "https://bucket.example"])
def test_unknown_storage_uri_is_rejected(uri: str):
    with pytest.raises(ValueError, match="unsupported storage URI"):
        infer_cloud(uri)


def test_production_cannot_use_ephemeral_local_storage(monkeypatch: pytest.MonkeyPatch):
    from jobs.common.config import get_settings

    monkeypatch.setenv("RP_ENV", "prod")
    monkeypatch.setenv("RP_LOCAL_ROOT", "/tmp/research")
    get_settings.cache_clear()
    try:
        with pytest.raises(Exception, match="forbidden"):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_matching_cloud_and_uri_pass():
    validate(Cloud.AWS, "s3://bucket")
    validate(Cloud.GCP, "gs://bucket")
    validate(Cloud.AZURE, "abfs://c@a.dfs.core.windows.net")


def test_every_provider_has_a_backend_and_a_log_conn():
    for cloud in (Cloud.GCP, Cloud.AWS, Cloud.AZURE):
        assert cloud in SECRETS_BACKEND
        assert cloud in LOG_CONN_ID


def test_settings_resolve_cloud_from_uri(monkeypatch: pytest.MonkeyPatch):
    from jobs.common.config import get_settings

    monkeypatch.delenv("RP_LOCAL_ROOT", raising=False)
    monkeypatch.setenv("RP_STORAGE_URI", "s3://research-bucket")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.cloud == Cloud.AWS
        assert settings.root_uri == "s3://research-bucket"
    finally:
        get_settings.cache_clear()


def test_settings_reject_a_contradictory_explicit_cloud(monkeypatch: pytest.MonkeyPatch):
    from jobs.common.config import get_settings

    monkeypatch.delenv("RP_LOCAL_ROOT", raising=False)
    monkeypatch.setenv("RP_STORAGE_URI", "gs://bucket")
    monkeypatch.setenv("RP_CLOUD", "aws")
    get_settings.cache_clear()
    try:
        with pytest.raises(Exception, match="does not start with"):
            get_settings()
    finally:
        get_settings.cache_clear()
