from __future__ import annotations

import typer
from pytest import MonkeyPatch, raises

from ctl.commands import deploy


def test_notebook_uses_local_compose_by_default() -> None:
    assert deploy._compose_files("notebook", {}, "/opt/research/notebook", "host") == [
        "/opt/research/notebook/compose/notebook.yml"
    ]


def test_notebook_efs_requires_an_absolute_mount() -> None:
    with raises(typer.Exit):
        deploy._compose_files(
            "notebook",
            {"NOTEBOOKS_HOST_PATH": "relative/notebooks"},
            "/opt/research/notebook",
            "host",
        )


def test_notebook_efs_fails_closed_and_adds_overlay(monkeypatch: MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(deploy, "sh", lambda command: calls.append(command))

    files = deploy._compose_files(
        "notebook",
        {"NOTEBOOKS_HOST_PATH": "/mnt/jarvis notebooks"},
        "/opt/research/notebook",
        "notebook-host",
    )

    assert calls == [
        [
            "ssh",
            "notebook-host",
            "test -d '/mnt/jarvis notebooks' && mountpoint -q -- '/mnt/jarvis notebooks'",
        ]
    ]
    assert files == [
        "/opt/research/notebook/compose/notebook.yml",
        "/opt/research/notebook/compose/notebook.efs.yml",
    ]
