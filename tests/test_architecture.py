"""Executable dependency rules for jobs and delivery tooling."""

import ast
from pathlib import Path


def test_jobs_do_not_depend_on_control_cli() -> None:
    for path in Path("jobs").rglob("*.py"):
        tree = ast.parse(path.read_text())
        imports = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        assert not any(name == "ctl" or name.startswith("ctl.") for name in imports), path


def test_deploy_never_copies_the_local_env_file() -> None:
    source = Path("ctl/commands/deploy.py").read_text()
    assert "ENV_FILE" not in source
    assert "runtime.env" in source


def test_control_compose_contains_only_secret_references() -> None:
    source = Path("compose/control.yml").read_text()
    assert "AIRFLOW_DB_PASSWORD" not in source
    assert "AIRFLOW_FERNET_KEY" not in source
    assert "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN:" not in source
    assert "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN_SECRET:" in source
    assert "AIRFLOW__CORE__FERNET_KEY_SECRET:" in source
