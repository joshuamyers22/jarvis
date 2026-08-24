"""Provider dispatch wiring.

Does not call any cloud. Asserts the mapping is complete and that the memory
conversion AWS Batch needs is right, because '4Gi' silently becoming 4 MiB is
the kind of unit bug that only shows up under load.
"""

from __future__ import annotations

import pytest

pytest.importorskip("airflow", reason="airflow not installed in this environment")

from dags._providers import DISPATCHERS, _memory_mib  # noqa: E402
from jobs.common.cloud import Cloud  # noqa: E402


def test_every_cloud_has_a_dispatcher():
    for cloud in (Cloud.GCP, Cloud.AWS, Cloud.AZURE):
        assert cloud in DISPATCHERS


@pytest.mark.parametrize(
    ("value", "expected"),
    [("4Gi", 4096), ("32Gi", 32768), ("512Mi", 512), ("2G", 2048), ("1024", 1024)],
)
def test_memory_quantities_convert_to_mib(value: str, expected: int):
    assert _memory_mib(value) == expected


def test_dispatchers_share_a_signature():
    """They are interchangeable or the abstraction is a lie."""
    import inspect

    signatures = {
        cloud: list(inspect.signature(fn).parameters) for cloud, fn in DISPATCHERS.items()
    }
    assert len(set(map(tuple, signatures.values()))) == 1, signatures
