"""Daily marked PnL.

Waits on the ingest DAG rather than duplicating the pull, so a re-run of ingest
does not silently produce two inconsistent views of the same day.
"""

from __future__ import annotations

import pendulum
from airflow.sdk import DAG
from airflow.sensors.external_task import ExternalTaskSensor

from dags._common import DEFAULT_ARGS, LOCAL_TZ, dispatch, verify

with DAG(
    dag_id="daily_pnl",
    description="Mark the book and compute daily PnL",
    start_date=pendulum.datetime(2026, 1, 1, tz=LOCAL_TZ),
    schedule="0 3 * * *",
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["derived", "pnl"],
) as dag:
    wait_for_bars = ExternalTaskSensor(
        task_id="wait_for_ohlcv",
        external_dag_id="hourly_ohlcv",
        external_task_id="verify_ohlcv",
        # hourly_ohlcv runs at 01:30, this DAG at 03:00, same logical date.
        execution_delta=pendulum.duration(hours=1, minutes=30),
        poke_interval=300,
        timeout=60 * 60 * 2,
        mode="reschedule",  # frees the worker slot while waiting
    )

    build = dispatch(
        "build_pnl",
        "build_pnl",
        cpu="2",
        memory="8Gi",
        timeout_seconds=3600,
    )

    check = verify.override(task_id="verify_pnl")(
        kind="derived",
        dataset="daily_pnl",
        ds="{{ ds }}",
    )

    wait_for_bars >> build >> check
