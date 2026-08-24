"""The job harness.

Every job module is a function ``run(ctx) -> JobResult`` plus one line of
boilerplate. The harness supplies the things that must be identical across all
jobs and are easy to get subtly wrong in each one:

* an explicit ``--date`` (never ``today()`` inside job logic -- that makes
  backfills and reruns non-reproducible)
* idempotency: a completed partition is skipped unless ``--force``
* an output-size assertion, so a job that writes an empty file fails loudly
  instead of reporting success
* the ``_SUCCESS`` marker that downstream tasks check
* a machine-readable result line on stdout for the dispatching DAG to read
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

from jobs.common import storage
from jobs.common.config import Settings, get_settings
from jobs.common.logging import get_logger

RESULT_PREFIX = "JOB_RESULT "


@dataclass(frozen=True)
class JobContext:
    name: str
    run_date: date
    run_id: str
    force: bool
    settings: Settings
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class JobResult:
    output_prefix: str
    rows: int
    metadata: dict[str, Any] = field(default_factory=dict)


JobFn = Callable[[JobContext], JobResult]


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:  # pragma: no cover - argparse renders this
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from exc


def build_parser(name: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"jobs.{name}")
    parser.add_argument(
        "--date",
        required=True,
        type=_parse_date,
        help="Logical date for this run (YYYY-MM-DD). Never defaulted on purpose.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Airflow run id, or any correlation id. Defaults to a timestamp.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recompute even if the partition is already marked complete.",
    )
    return parser


def main(name: str, run: JobFn, argv: list[str] | None = None) -> int:
    """Entry point shared by every job module."""
    log = get_logger(f"jobs.{name}")
    parser = build_parser(name)
    args = parser.parse_args(argv)

    settings = get_settings()
    run_id = args.run_id or f"manual__{int(time.time())}"
    ctx = JobContext(
        name=name,
        run_date=args.date,
        run_id=run_id,
        force=args.force,
        settings=settings,
        extra={},
    )

    log.info(
        "job.start",
        extra={
            "job": name,
            "run_date": ctx.run_date.isoformat(),
            "run_id": run_id,
            "env": settings.env,
        },
    )
    started = time.monotonic()

    try:
        result = run(ctx)
    except Exception:
        log.error("job.failed", extra={"job": name, "trace": traceback.format_exc()})
        return 1

    written = storage.size_bytes(result.output_prefix)
    if written < settings.min_output_bytes:
        # The failure mode this exists to catch: an upstream API returns an
        # empty body, the job writes a zero-row parquet, every downstream task
        # succeeds, and the gap is discovered a month later.
        log.error(
            "job.output_too_small",
            extra={"job": name, "bytes": written, "minimum": settings.min_output_bytes},
        )
        return 1

    metadata = {
        "job": name,
        "run_date": ctx.run_date.isoformat(),
        "run_id": run_id,
        "rows": result.rows,
        "bytes": written,
        "completed_at": datetime.now().astimezone().isoformat(),
        **result.metadata,
    }
    storage.mark_success(result.output_prefix, metadata)

    elapsed = time.monotonic() - started
    log.info("job.done", extra={**metadata, "seconds": round(elapsed, 2)})
    # Parsed by the dispatching DAG; keep the format stable.
    print(RESULT_PREFIX + json.dumps(asdict(result) | {"bytes": written}), flush=True)
    return 0


def entrypoint(name: str, run: JobFn) -> None:
    """``if __name__ == '__main__': entrypoint('pull_ohlcv', run)``"""
    sys.exit(main(name, run))


def skip_if_complete(ctx: JobContext, prefix: str) -> bool:
    """True when this partition is already done and the run is not forced."""
    if ctx.force:
        storage.clear_success(prefix)
        return False
    if storage.is_complete(prefix):
        get_logger(f"jobs.{ctx.name}").info(
            "job.skipped_complete", extra={"job": ctx.name, "prefix": prefix}
        )
        return True
    return False
