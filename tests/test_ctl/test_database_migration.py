from __future__ import annotations

import json

from pytest import MonkeyPatch

from ctl import database_migration
from ctl.database_migration import assess_migration_heads


def assess(database_heads: list[str], *, dialect: str = "postgresql"):
    return assess_migration_heads(
        database_heads,
        ["head"],
        ["head", "middle", "base"],
        database_dialect=dialect,
        airflow_version="3.3.2",
    )


def test_uninitialized_postgres_database_can_be_initialized() -> None:
    state = assess([])

    assert state.compatible is True
    assert state.state == "uninitialized"


def test_ancestor_revision_requires_forward_migration() -> None:
    state = assess(["middle"])

    assert state.compatible is True
    assert state.state == "upgrade-required"


def test_exact_candidate_head_is_current() -> None:
    state = assess(["head"])

    assert state.compatible is True
    assert state.state == "current"


def test_newer_or_divergent_database_is_rejected() -> None:
    state = assess(["future"])

    assert state.compatible is False
    assert state.state == "incompatible"
    assert state.error == "database revision is not in the candidate image migration ancestry"


def test_non_postgres_database_is_rejected_without_a_lock_contract() -> None:
    state = assess(["head"], dialect="sqlite")

    assert state.compatible is False
    assert state.error == "production migrations require PostgreSQL advisory locking"


def test_current_mode_emits_one_json_object(monkeypatch: MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(database_migration, "inspect_migration_state", lambda: assess(["head"]))

    assert database_migration.main(["current"]) == 0
    lines = capsys.readouterr().out.splitlines()

    assert len(lines) == 1
    assert json.loads(lines[0])["state"] == "current"


def test_current_mode_rejects_a_compatible_but_unmigrated_database(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(database_migration, "inspect_migration_state", lambda: assess(["middle"]))

    assert database_migration.main(["preflight"]) == 0
    assert database_migration.main(["current"]) == 1
