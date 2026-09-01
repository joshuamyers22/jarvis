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
