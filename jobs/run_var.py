"""Historical-simulation VaR and expected shortfall over the current book.

Template for a compute-heavy job: reads a wide history, produces a small
artifact. Sized differently from the ingest jobs in the batch job definition,
which is the whole reason for per-task sizing.
"""

from __future__ import annotations

import os
from datetime import timedelta

import numpy as np
import pandas as pd

from jobs.common import storage
from jobs.common.harness import JobContext, JobResult, entrypoint, skip_if_complete
from jobs.common.logging import get_logger

log = get_logger("jobs.run_var")

DATASET = "var"
LOOKBACK_DAYS = int(os.environ.get("RP_VAR_LOOKBACK_DAYS", "500"))
CONFIDENCE_LEVELS = (0.95, 0.99)


def _load_history(ctx: JobContext) -> pd.DataFrame:
    start = ctx.run_date - timedelta(days=LOOKBACK_DAYS)
    frame = storage.read_parquet(storage.dataset_glob("derived", "daily_pnl"))
    frame["dt"] = pd.to_datetime(frame["dt"]).dt.date
    window = frame[(frame["dt"] > start) & (frame["dt"] <= ctx.run_date)]
    if window.empty:
        raise RuntimeError(f"no PnL history in window {start}..{ctx.run_date}")
    return window


def run(ctx: JobContext) -> JobResult:
    prefix = storage.derived_prefix(DATASET, ctx.run_date)
    if skip_if_complete(ctx, prefix):
        return JobResult(output_prefix=prefix, rows=0, metadata={"skipped": True})

    history = _load_history(ctx)
    daily = history.groupby("dt", as_index=False)["pnl"].sum().sort_values("dt")

    observations = len(daily)
    if observations < 60:
        # Below this, the tail quantile is an artefact of one or two days.
        raise RuntimeError(f"only {observations} observations; refusing to estimate VaR")

    losses = -daily["pnl"].to_numpy(dtype=float)

    rows = []
    for level in CONFIDENCE_LEVELS:
        var = float(np.quantile(losses, level))
        tail = losses[losses >= var]
        es = float(tail.mean()) if tail.size else var
        rows.append(
            {
                "dt": pd.Timestamp(ctx.run_date),
                "confidence": level,
                "var": var,
                "expected_shortfall": es,
                "observations": observations,
                "lookback_days": LOOKBACK_DAYS,
            }
        )
        log.info(
            "var.computed",
            extra={"confidence": level, "var": var, "es": es, "n": observations},
        )

    result = pd.DataFrame(rows)
    storage.write_parquet(result, prefix)
    return JobResult(
        output_prefix=prefix,
        rows=len(result),
        metadata={"observations": observations},
    )


if __name__ == "__main__":
    entrypoint("run_var", run)
