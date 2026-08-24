from __future__ import annotations

from datetime import date

import pandas as pd

from jobs.common import storage
from jobs.common.harness import JobContext, JobResult, main


def _write(prefix: str, rows: int) -> None:
    storage.write_parquet(pd.DataFrame({"a": range(rows)}), prefix)


def test_successful_run_marks_the_partition():
    def run(ctx: JobContext) -> JobResult:
        prefix = storage.derived_prefix("harness", ctx.run_date)
        _write(prefix, 100)
        return JobResult(output_prefix=prefix, rows=100)

    assert main("harness", run, ["--date", "2026-08-11"]) == 0
    assert storage.is_complete(storage.derived_prefix("harness", date(2026, 8, 11)))


def test_empty_output_fails_instead_of_silently_succeeding():
    """The failure this whole design exists to prevent."""

    def run(ctx: JobContext) -> JobResult:
        prefix = storage.derived_prefix("empty", ctx.run_date)
        storage.write_json(f"{prefix}/placeholder.json", {})
        return JobResult(output_prefix=prefix, rows=0)

    import os

    os.environ["RP_MIN_OUTPUT_BYTES"] = "100000"
    from jobs.common.config import get_settings

    get_settings.cache_clear()
    try:
        assert main("empty", run, ["--date", "2026-08-11"]) == 1
        assert not storage.is_complete(storage.derived_prefix("empty", date(2026, 8, 11)))
    finally:
        del os.environ["RP_MIN_OUTPUT_BYTES"]
        get_settings.cache_clear()


def test_exception_returns_nonzero_and_leaves_no_marker():
    def run(ctx: JobContext) -> JobResult:
        raise RuntimeError("upstream exploded")

    assert main("boom", run, ["--date", "2026-08-11"]) == 1


def test_date_is_required():
    """No default date, ever -- it makes backfills non-reproducible."""
    import pytest

    def run(ctx: JobContext) -> JobResult:  # pragma: no cover
        raise AssertionError("should not be reached")

    with pytest.raises(SystemExit):
        main("nodate", run, [])


def test_completed_partition_is_skipped_unless_forced():
    calls = {"n": 0}

    def run(ctx: JobContext) -> JobResult:
        from jobs.common.harness import skip_if_complete

        prefix = storage.derived_prefix("idem", ctx.run_date)
        if skip_if_complete(ctx, prefix):
            return JobResult(output_prefix=prefix, rows=0, metadata={"skipped": True})
        calls["n"] += 1
        _write(prefix, 50)
        return JobResult(output_prefix=prefix, rows=50)

    assert main("idem", run, ["--date", "2026-08-11"]) == 0
    assert main("idem", run, ["--date", "2026-08-11"]) == 0
    assert calls["n"] == 1

    assert main("idem", run, ["--date", "2026-08-11", "--force"]) == 0
    assert calls["n"] == 2


def test_forced_run_hides_stale_success_marker_while_replacing_data():
    prefix = storage.derived_prefix("replace", date(2026, 8, 11))

    def run(ctx: JobContext) -> JobResult:
        if storage.is_complete(prefix):
            from jobs.common.harness import skip_if_complete

            assert not skip_if_complete(ctx, prefix)
            assert not storage.is_complete(prefix)
        _write(prefix, 10)
        return JobResult(output_prefix=prefix, rows=10)

    assert main("replace", run, ["--date", "2026-08-11"]) == 0
    assert main("replace", run, ["--date", "2026-08-11", "--force"]) == 0
    assert storage.is_complete(prefix)


def test_unknown_arguments_fail_fast():
    import pytest

    def run(ctx: JobContext) -> JobResult:  # pragma: no cover
        raise AssertionError("should not run")

    with pytest.raises(SystemExit):
        main("strict", run, ["--date", "2026-08-11", "--typo"])
