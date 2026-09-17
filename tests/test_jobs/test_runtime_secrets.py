from __future__ import annotations

import pytest

from jobs.common.runtime_secrets import credential_headers, resolved_environment


def test_runtime_secret_reference_is_resolved_into_child_only() -> None:
    source = {
        "RP_ENV": "prod",
        "RP_STORAGE_URI": "gs://research-data",
        "RP_VENDOR_CREDENTIAL_SECRET_ID": "vendor-id",
    }
    calls = []

    def fetcher(cloud, reference, env):
        calls.append((cloud, reference))
        return '{"headers":{"Authorization":"Bearer value"}}'

    child = resolved_environment("job", source, fetcher=fetcher)

    assert calls == [("gcp", "vendor-id")]
    assert "RP_VENDOR_CREDENTIAL" not in source
    assert credential_headers("RP_VENDOR_CREDENTIAL", child) == {"Authorization": "Bearer value"}


def test_production_runtime_fails_closed_without_reference() -> None:
    with pytest.raises(RuntimeError, match="RP_FEED_CREDENTIAL_SECRET_ID"):
        resolved_environment("feed", {"RP_ENV": "prod", "RP_CLOUD": "gcp"})


def test_development_runtime_may_run_without_credentials() -> None:
    source = {"RP_ENV": "dev", "RP_CLOUD": "local"}
    assert resolved_environment("feed", source) == source


@pytest.mark.parametrize(
    "value",
    ["not-json", "[]", '{"headers":[]}', '{"headers":{"X":1}}'],
)
def test_credential_contract_rejects_invalid_values(value: str) -> None:
    with pytest.raises(RuntimeError, match="headers"):
        credential_headers("RP_VENDOR_CREDENTIAL", {"RP_VENDOR_CREDENTIAL": value})
