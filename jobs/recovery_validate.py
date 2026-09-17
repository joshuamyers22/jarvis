"""Validate a temporary recovery target from inside the private GCP network."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

import psycopg2
from sqlalchemy.engine import make_url

from jobs.common.cloud import fetch_secret

RESULT_MARKER = "JARVIS_RECOVERY_RESULT="


def validate_database(target_host: str, env: dict[str, str]) -> dict[str, object]:
    project = env.get("RP_PROJECT_ID")
    if not project:
        raise RuntimeError("RP_PROJECT_ID is required")
    source = fetch_secret("gcp", "airflow-config-sql-alchemy-conn", env)
    target_url = make_url(source).set(host=target_host).update_query_dict({"connect_timeout": "10"})
    dsn = target_url.render_as_string(hide_password=False)

    counts: dict[str, int] = {}
    with (
        psycopg2.connect(
            host=target_host,
            port=target_url.port or 5432,
            user=target_url.username,
            password=target_url.password,
            dbname=target_url.database,
            sslmode=target_url.query.get("sslmode", "require"),
            connect_timeout=10,
        ) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_database(), current_user")
        database, user = cursor.fetchone()
        cursor.execute("SELECT version_num FROM alembic_version")
        migration_version = cursor.fetchone()[0]
        for table in ("dag", "dag_run"):
            cursor.execute(f'SELECT COUNT(*) FROM "{table}"')  # noqa: S608
            counts[table] = cursor.fetchone()[0]

    airflow_env = dict(env)
    airflow_env["AIRFLOW__DATABASE__SQL_ALCHEMY_CONN"] = dsn
    check = subprocess.run(
        ["airflow", "db", "check"],
        env=airflow_env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if check.returncode:
        raise RuntimeError("Airflow database smoke test failed")
    return {
        "sql_query": "passed",
        "airflow_db_check": "passed",
        "database": database,
        "user": user,
        "migration_version": migration_version,
        "table_counts": counts,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)
    database = subparsers.add_parser("database")
    database.add_argument("--target-host", required=True)
    args = parser.parse_args(argv)

    try:
        result = validate_database(args.target_host, dict(os.environ))
    except Exception as exc:
        # Do not print an SDK/database exception: it can contain connection
        # material. The outer drill records only this sanitized failure class.
        print(f"recovery validation failed ({type(exc).__name__})", file=sys.stderr)
        raise SystemExit(1) from None
    print(RESULT_MARKER + json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
