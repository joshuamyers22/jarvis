from __future__ import annotations

import stat

import typer
from pytest import MonkeyPatch, raises

from ctl.commands import deploy
from ctl.commands._util import deployment_env, deployment_env_file


def test_notebook_uses_local_compose_by_default() -> None:
    assert deploy._compose_files("notebook", {}, "/opt/research/notebook", "host") == [
        "/opt/research/notebook/compose/notebook.yml"
    ]


def test_gcp_service_activation_is_enabled_restarted_and_health_gated(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(deploy, "sh", lambda command: calls.append(command))

    deploy._activate_gcp_service("operator@control", "control")

    assert calls == [
        [
            "ssh",
            "operator@control",
            "sudo systemctl enable jarvis-compose@control.service",
        ],
        [
            "ssh",
            "operator@control",
            "sudo systemctl restart jarvis-compose@control.service",
        ],
        [
            "ssh",
            "operator@control",
            "sudo /usr/local/sbin/jarvis-compose wait control 300",
        ],
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


def test_deployment_environment_is_an_explicit_non_secret_allowlist() -> None:
    selected = deployment_env(
        {
            "IMAGE": "registry/image",
            "RP_ENV": "prod",
            "RP_FEED_CREDENTIAL_SECRET_ID": "feed-secret-id",
            "CONTROL_HOST": "private-host",
            "UNREVIEWED_SETTING": "stays-local",
        }
    )

    assert selected == {
        "IMAGE": "registry/image",
        "RP_ENV": "prod",
        "RP_FEED_CREDENTIAL_SECRET_ID": "feed-secret-id",
    }


def test_deployment_environment_rejects_secret_values_without_printing_them(
    capsys,
) -> None:
    with raises(typer.Exit):
        deployment_env({"AIRFLOW_DB_PASSWORD": "super-secret-value"})

    output = capsys.readouterr().out
    assert "AIRFLOW_DB_PASSWORD" in output
    assert "super-secret-value" not in output


def test_runtime_environment_file_is_private_and_ephemeral() -> None:
    with deployment_env_file({"RP_ENV": "prod"}) as path:
        assert path.read_text() == "RP_ENV=prod\n"
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    assert not path.exists()
