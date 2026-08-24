"""Pull hourly OHLCV bars for one logical date.

Template job. Swap ``_fetch_bars`` for your vendor's client; everything around
it -- retries, partitioning, idempotency, the completion marker -- is the part
worth keeping.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, time, timedelta

import httpx
import pandas as pd
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from jobs.common import storage
from jobs.common.harness import JobContext, JobResult, entrypoint, skip_if_complete
from jobs.common.logging import get_logger

log = get_logger("jobs.pull_ohlcv")

SOURCE = os.environ.get("RP_OHLCV_SOURCE", "vendor")
DATASET = "ohlcv_hourly"
BASE_URL = os.environ.get("RP_OHLCV_BASE_URL", "")
SYMBOLS = [s for s in os.environ.get("RP_OHLCV_SYMBOLS", "").split(",") if s]

COLUMNS = ["symbol", "ts", "open", "high", "low", "close", "volume"]


@retry(
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(5),
    reraise=True,
)
def _fetch_bars(client: httpx.Client, symbol: str, start: datetime, end: datetime) -> list[dict]:
    """One symbol, one day of hourly bars.

    Replace the request shape with your vendor's. The retry policy is the
    reusable part: exponential backoff on transport errors only, so a 400 fails
    immediately instead of being retried five times.
    """
    response = client.get(
        f"{BASE_URL}/ohlcv",
        params={
            "symbol": symbol,
            "interval": "1h",
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        timeout=30.0,
    )
    response.raise_for_status()
    return response.json().get("bars", [])


def run(ctx: JobContext) -> JobResult:
    prefix = storage.raw_prefix(SOURCE, DATASET, ctx.run_date)
    if skip_if_complete(ctx, prefix):
        return JobResult(output_prefix=prefix, rows=0, metadata={"skipped": True})

    if not BASE_URL or not SYMBOLS:
        raise RuntimeError("RP_OHLCV_BASE_URL and RP_OHLCV_SYMBOLS must both be set")

    start = datetime.combine(ctx.run_date, time.min, tzinfo=UTC)
    end = start + timedelta(days=1)

    frames: list[pd.DataFrame] = []
    with httpx.Client() as client:
        for symbol in SYMBOLS:
            bars = _fetch_bars(client, symbol, start, end)
            if not bars:
                log.warning("ohlcv.empty_symbol", extra={"symbol": symbol})
                continue
            frame = pd.DataFrame(bars)
            frame["symbol"] = symbol
            frames.append(frame)
            log.info("ohlcv.fetched", extra={"symbol": symbol, "rows": len(frame)})

    if not frames:
        raise RuntimeError(f"no bars returned for any of {len(SYMBOLS)} symbols")

    df = pd.concat(frames, ignore_index=True)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.reindex(columns=COLUMNS).sort_values(["symbol", "ts"]).reset_index(drop=True)

    # Bar counts vary legitimately (holidays, listings), so this is a warning
    # rather than a failure. Silence here would be worse than a false positive.
    expected = 24 * len(SYMBOLS)
    if len(df) < expected * 0.5:
        log.warning("ohlcv.suspicious_row_count", extra={"rows": len(df), "expected": expected})

    storage.write_parquet(df, prefix)
    return JobResult(
        output_prefix=prefix,
        rows=len(df),
        metadata={"symbols": len(SYMBOLS), "source": SOURCE},
    )


if __name__ == "__main__":
    entrypoint("pull_ohlcv", run)
