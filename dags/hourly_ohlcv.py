"""Hourly OHLCV ingest.

Scheduled daily rather than hourly on purpose: the job pulls a full day of
hourly bars in one request per symbol, which is cheaper and produces one
partition per day instead of 24 tiny ones. Small files are the most common
self-inflicted wound in a parquet lake.
"""

from __future__ import annotations

import pendulum
from airflow.sdk import DAG

from dags._common import DEFAULT_ARGS, LOCAL_TZ, dispatch, verify

with DAG(
    dag_id="hourly_ohlcv",
    description="Pull one day of hourly OHLCV bars into raw/",
    start_date=pendulum.datetime(2026, 1, 1, tz=LOCAL_TZ),
    schedule="30 1 * * *",  # after the vendor's own end-of-day settle
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["ingest", "market-data"],
) as dag:
    pull = dispatch(
        "pull_ohlcv",
        "pull_ohlcv",
        cpu="1",
        memory="2Gi",
        timeout_seconds=1800,
    )

    check = verify.override(task_id="verify_ohlcv")(
        kind="raw",
        dataset="ohlcv_hourly",
        source="vendor",
        ds="{{ ds }}",
    )

    pull >> check
