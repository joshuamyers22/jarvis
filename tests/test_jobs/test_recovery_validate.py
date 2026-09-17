from __future__ import annotations

import subprocess

from pytest import MonkeyPatch

from jobs import recovery_validate


class FakeCursor:
    def __init__(self) -> None:
        self.results = iter(
            [
                ("airflow", "airflow"),
                ("abc123",),
                (12,),
                (34,),
            ]
        )

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, _query: str) -> None:
        return None

    def fetchone(self):
        return next(self.results)


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self) -> FakeCursor:
        return FakeCursor()


def test_database_restore_validation_uses_secret_without_returning_it(
    monkeypatch: MonkeyPatch,
) -> None:
    password = "never-record-this-password"
    connection_args = {}

    monkeypatch.setattr(
        recovery_validate,
        "fetch_secret",
        lambda *_args: (
            f"postgresql+psycopg2://airflow:{password}@10.0.0.1:5432/airflow?sslmode=require"
        ),
    )

    def connect(**kwargs):
        connection_args.update(kwargs)
        return FakeConnection()

    monkeypatch.setattr(recovery_validate.psycopg2, "connect", connect)
    monkeypatch.setattr(
        recovery_validate.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "", ""),
    )

    result = recovery_validate.validate_database(
        "10.20.30.40", {"RP_PROJECT_ID": "jarvis-research-stage"}
    )

    assert connection_args["host"] == "10.20.30.40"
    assert connection_args["password"] == password
    assert result["sql_query"] == "passed"
    assert result["airflow_db_check"] == "passed"
    assert password not in str(result)
