"""Nightly VaR / expected shortfall.

The heaviest job in the project and the clearest argument for per-task sizing:
it asks for 32 GiB while the ingest DAG asks for 2, from the same image.
"""

from __future__ import annotations

import pendulum
from airflow.sdk import DAG
from airflow.sensors.external_task import ExternalTaskSensor

from dags._common import DEFAULT_ARGS, LOCAL_TZ, dispatch, verify

with DAG(
    dag_id="nightly_risk",
    description="Historical-simulation VaR and ES over the current book",
    start_date=pendulum.datetime(2026, 1, 1, tz=LOCAL_TZ),
    schedule="0 5 * * 1-5",  # weekdays only
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["derived", "risk"],
) as dag:
    wait_for_pnl = ExternalTaskSensor(
        task_id="wait_for_pnl",
        external_dag_id="daily_pnl",
        external_task_id="verify_pnl",
        execution_delta=pendulum.duration(hours=2),
        poke_interval=300,
        timeout=60 * 60 * 2,
        mode="reschedule",
    )

    var = dispatch(
        "run_var",
        "run_var",
        env={"RP_VAR_LOOKBACK_DAYS": "500"},
        cpu="8",
        memory="32Gi",
        timeout_seconds=7200,
    )

    check = verify.override(task_id="verify_var")(
        kind="derived",
        dataset="var",
        ds="{{ ds }}",
    )

    wait_for_pnl >> var >> check
