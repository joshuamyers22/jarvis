"""Derive daily marked PnL from raw bars and a positions snapshot.

Second template: a job whose inputs are other partitions rather than an API.
The pattern to copy is the explicit dependency check at the top -- reading a
partition that exists but has no ``_SUCCESS`` marker means reading a partition
that may still be being written.
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from jobs.common import storage
from jobs.common.harness import JobContext, JobResult, entrypoint, skip_if_complete
from jobs.common.logging import get_logger

log = get_logger("jobs.build_pnl")

DATASET = "daily_pnl"
BARS_SOURCE = "vendor"
BARS_DATASET = "ohlcv_hourly"
POSITIONS_DATASET = "positions"


def _require_complete(prefix: str, label: str) -> pd.DataFrame:
    if not storage.is_complete(prefix):
        raise RuntimeError(f"upstream {label} is not marked complete: {prefix}")
    return storage.read_parquet(f"{prefix}/*.parquet")


def run(ctx: JobContext) -> JobResult:
    prefix = storage.derived_prefix(DATASET, ctx.run_date)
    if skip_if_complete(ctx, prefix):
        return JobResult(output_prefix=prefix, rows=0, metadata={"skipped": True})

    prev_date = ctx.run_date - timedelta(days=1)

    bars = _require_complete(storage.raw_prefix(BARS_SOURCE, BARS_DATASET, ctx.run_date), "bars")
    positions = _require_complete(storage.derived_prefix(POSITIONS_DATASET, prev_date), "positions")

    # Last bar of the day is the mark.
    closes = (
        bars.sort_values("ts")
        .groupby("symbol", as_index=False)
        .last()[["symbol", "close"]]
        .rename(columns={"close": "mark"})
    )

    merged = positions.merge(closes, on="symbol", how="left", validate="one_to_one")

    unmarked = merged["mark"].isna()
    if unmarked.any():
        # A position with no mark is a real problem, not a rounding issue: it
        # silently contributes zero PnL. Fail rather than under-report.
        missing = merged.loc[unmarked, "symbol"].tolist()
        raise RuntimeError(f"no mark for {len(missing)} held symbols: {missing[:10]}")

    merged["market_value"] = merged["quantity"] * merged["mark"] * merged.get("multiplier", 1)
    merged["pnl"] = (
        merged["quantity"] * (merged["mark"] - merged["prev_mark"]) * merged.get("multiplier", 1)
    )
    merged["dt"] = pd.Timestamp(ctx.run_date)

    total = float(merged["pnl"].sum())
    log.info("pnl.computed", extra={"positions": len(merged), "total_pnl": total})

    storage.write_parquet(merged, prefix)
    return JobResult(
        output_prefix=prefix,
        rows=len(merged),
        metadata={"total_pnl": total, "positions": len(merged)},
    )


if __name__ == "__main__":
    entrypoint("build_pnl", run)
