"""Long-running websocket consumer.

Deliberately not an Airflow task. This process is expected to run forever, and
the failure mode that matters is a connection that dies quietly while the
supervisor still reports healthy -- which is exactly what happens when you try
to make a scheduler own a daemon.

Guarantees:
  * reconnects with exponential backoff and jitter, indefinitely
  * flushes buffered rows on a timer, on a row count, and on SIGTERM
  * a heartbeat log even when no messages arrive, so silence is distinguishable
    from a dead socket
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import random
import signal
import time
from datetime import UTC, datetime

import pandas as pd
import websockets

from jobs.common import storage
from jobs.common.config import get_settings
from jobs.common.logging import get_logger

log = get_logger("jobs.feed")

HEARTBEAT_SECONDS = 30


class Buffer:
    """In-memory batch, flushed to a timestamped parquet part file."""

    def __init__(self, source: str, dataset: str) -> None:
        self._rows: list[dict] = []
        self._source = source
        self._dataset = dataset
        self._last_flush = time.monotonic()

    def __len__(self) -> int:
        return len(self._rows)

    def add(self, row: dict) -> None:
        self._rows.append(row)

    @property
    def seconds_since_flush(self) -> float:
        return time.monotonic() - self._last_flush

    def flush(self) -> int:
        self._last_flush = time.monotonic()
        if not self._rows:
            return 0
        rows, self._rows = self._rows, []
        frame = pd.DataFrame(rows)
        now = datetime.now(UTC)
        prefix = storage.raw_prefix(self._source, self._dataset, now.date())
        # Part name carries the wall-clock time, so concurrent restarts cannot
        # overwrite each other's data.
        name = f"part-{now.strftime('%H%M%S%f')}.parquet"
        uri = storage.write_parquet(frame, prefix, filename=name)
        log.info("feed.flushed", extra={"rows": len(rows), "uri": uri})
        return len(rows)


def parse_message(raw: str | bytes) -> dict | None:
    """Vendor-specific. Return None to drop a message (heartbeats, acks)."""
    payload = json.loads(raw)
    if payload.get("type") != "tick":
        return None
    return {
        "ts": pd.to_datetime(payload["timestamp"], utc=True),
        "symbol": payload["symbol"],
        "price": float(payload["price"]),
        "size": float(payload.get("size", 0.0)),
        "received_at": datetime.now(UTC),
    }


async def _flusher(buffer: Buffer, stop: asyncio.Event) -> None:
    settings = get_settings()
    while not stop.is_set():
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=5.0)
        if buffer.seconds_since_flush >= settings.feed_flush_seconds:
            buffer.flush()


async def _consume(buffer: Buffer, stop: asyncio.Event) -> None:
    settings = get_settings()
    backoff = 1.0
    last_heartbeat = time.monotonic()

    while not stop.is_set():
        try:
            async with websockets.connect(
                settings.feed_ws_url, ping_interval=20, ping_timeout=20
            ) as socket:
                log.info("feed.connected", extra={"url": settings.feed_ws_url})
                backoff = 1.0  # only reset after a *successful* connect

                while not stop.is_set():
                    try:
                        raw = await asyncio.wait_for(socket.recv(), timeout=HEARTBEAT_SECONDS)
                    except TimeoutError:
                        # No data is not the same as no connection. Say so.
                        log.info("feed.idle", extra={"buffered": len(buffer)})
                        last_heartbeat = time.monotonic()
                        continue

                    row = parse_message(raw)
                    if row is not None:
                        buffer.add(row)

                    if len(buffer) >= settings.feed_flush_rows:
                        buffer.flush()

                    if time.monotonic() - last_heartbeat > HEARTBEAT_SECONDS:
                        log.info("feed.alive", extra={"buffered": len(buffer)})
                        last_heartbeat = time.monotonic()

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Never lose what is already buffered to a reconnect.
            buffer.flush()
            sleep_for = min(backoff, settings.feed_max_backoff_seconds)
            sleep_for *= 0.5 + random.random()  # jitter: avoid synchronised retries
            log.warning(
                "feed.disconnected",
                extra={"error": repr(exc), "retry_in": round(sleep_for, 2)},
            )
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=sleep_for)
            backoff = min(backoff * 2, settings.feed_max_backoff_seconds)


async def amain() -> None:
    settings = get_settings()
    if not settings.feed_ws_url:
        raise RuntimeError("RP_FEED_WS_URL is not set")

    buffer = Buffer(settings.feed_source, settings.feed_dataset)
    stop = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    log.info("feed.starting", extra={"source": settings.feed_source})
    consumer = asyncio.create_task(_consume(buffer, stop))
    flusher = asyncio.create_task(_flusher(buffer, stop))

    await stop.wait()
    log.info("feed.stopping", extra={"buffered": len(buffer)})

    for task in (consumer, flusher):
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    buffer.flush()  # the point of the SIGTERM handler
    log.info("feed.stopped")


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
