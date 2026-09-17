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


def test_gcp_control_candidate_is_checked_before_activation(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(deploy, "sh", lambda command: calls.append(command))

    deploy._check_database_compatibility("operator@control", "gcp", "/opt/research/control")

    assert len(calls) == 2
    assert ".env.migration-pending" in calls[0][2]
    assert calls[1] == [
        "ssh",
        "operator@control",
        "sudo /usr/local/sbin/jarvis-compose migration-current control",
    ]


def test_portable_control_candidate_uses_one_off_migration_service(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(deploy, "sh", lambda command: calls.append(command))

    deploy._check_database_compatibility("operator@control", "aws", "/opt/research/control")

    assert len(calls) == 3
    assert ".env.migration-pending" in calls[0][2]
    assert calls[1][:2] == ["ssh", "operator@control"]
    assert ".env.candidate-tag" in calls[1][2]
    assert calls[1][2].endswith("pull migration")
    assert calls[2][2].endswith("run --rm --no-deps migration migration-current")


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
        {
            "NOTEBOOKS_HOST_PATH": "/mnt/jarvis notebooks",
            "RP_NOTEBOOK_STORAGE_MODE": "aws-efs",
            "RP_NOTEBOOK_STORAGE_ID": "fs-0123456789abcdef0",
            "RP_NOTEBOOK_STORAGE_ACCESS_POINT_ID": "fsap-0123456789abcdef0",
        },
        "/opt/research/notebook",
        "notebook-host",
    )

    assert len(calls) == 1
    assert calls[0][:2] == ["ssh", "notebook-host"]
    assert "mountpoint -q -- '/mnt/jarvis notebooks'" in calls[0][2]
    assert "findmnt -n -t nfs4" in calls[0][2]
    assert "fs-0123456789abcdef0:/" in calls[0][2]
    assert "accesspoint=fsap-0123456789abcdef0" in calls[0][2]
    assert "$1 == source" in calls[0][2]
    assert "/etc/fstab" in calls[0][2]
    assert files == [
        "/opt/research/notebook/compose/notebook.yml",
        "/opt/research/notebook/compose/notebook.storage.yml",
    ]


def test_notebook_storage_requires_declared_mode(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(deploy, "sh", lambda command: None)

    with raises(typer.Exit):
        deploy._compose_files(
            "notebook",
            {"NOTEBOOKS_HOST_PATH": "/mnt/jarvis-notebooks"},
            "/opt/research/notebook",
            "notebook-host",
        )


def test_gcp_notebook_disk_uses_baked_verifier(monkeypatch: MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(deploy, "sh", lambda command: calls.append(command))

    files = deploy._compose_files(
        "notebook",
        {
            "NOTEBOOKS_HOST_PATH": "/mnt/jarvis-notebooks",
            "RP_NOTEBOOK_STORAGE_MODE": "gcp-pd",
            "RP_NOTEBOOK_STORAGE_ID": "research-prod-notebooks",
        },
        "/opt/research/notebook",
        "notebook-host",
    )

    assert calls == [
        [
            "ssh",
            "notebook-host",
            "sudo /usr/local/sbin/jarvis-notebook-storage verify /mnt/jarvis-notebooks",
        ]
    ]
    assert files[-1].endswith("notebook.storage.yml")


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
