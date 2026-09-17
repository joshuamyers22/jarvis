from __future__ import annotations

import typer
from pytest import MonkeyPatch, raises

from ctl.commands import migrate


def test_gcp_migration_preflights_then_stops_then_migrates(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(migrate, "sh", lambda command: calls.append(command))

    migrate._run_migration("operator@control", "gcp", "/opt/research/control")

    assert calls == [
        [
            "ssh",
            "operator@control",
            "sudo /usr/local/sbin/jarvis-compose migration-preflight control",
        ],
        [
            "ssh",
            "operator@control",
            "sudo systemctl stop jarvis-compose@control.service",
        ],
        [
            "ssh",
            "operator@control",
            "cp /opt/research/control/.env.migration-tag "
            "/opt/research/control/.env.migration-pending && "
            "chmod 600 /opt/research/control/.env.migration-pending",
        ],
        [
            "ssh",
            "operator@control",
            "sudo /usr/local/sbin/jarvis-compose migrate control",
        ],
    ]


def test_production_requires_backup_evidence_before_resolving_a_tag(
    monkeypatch: MonkeyPatch,
) -> None:
    resolved = False

    def resolve(*args, **kwargs):
        nonlocal resolved
        resolved = True
        return "candidate"

    monkeypatch.setattr(migrate, "load_env", lambda: {"RP_ENV": "prod"})
    monkeypatch.setattr(migrate, "resolve_tag", resolve)

    with raises(typer.Exit):
        migrate.migrate(tag="candidate", backup_reference=None, allow_dirty=True)

    assert resolved is False


def test_backup_reference_must_be_single_line(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(migrate, "load_env", lambda: {"RP_ENV": "stage"})

    with raises(typer.Exit):
        migrate.migrate(
            tag="candidate",
            backup_reference="backup\nforged-log-line",
            allow_dirty=True,
        )
