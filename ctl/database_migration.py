"""Inspect Airflow metadata-schema compatibility without exposing its DSN."""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class MigrationState:
    schema_version: int
    airflow_version: str
    database_dialect: str
    database_heads: tuple[str, ...]
    image_heads: tuple[str, ...]
    state: str
    compatible: bool
    error: str | None = None


def assess_migration_heads(
    database_heads: Iterable[str],
    image_heads: Iterable[str],
    image_revisions: Iterable[str],
    *,
    database_dialect: str,
    airflow_version: str,
) -> MigrationState:
    """Classify the database against the migration graph shipped in one image."""
    database = tuple(sorted(set(database_heads)))
    image = tuple(sorted(set(image_heads)))
    known = set(image_revisions)

    state = "incompatible"
    compatible = False
    error: str | None = None
    if database_dialect != "postgresql":
        error = "production migrations require PostgreSQL advisory locking"
    elif not image:
        error = "candidate image has no Airflow migration head"
    elif not database:
        state = "uninitialized"
        compatible = True
    elif set(database) == set(image):
        state = "current"
        compatible = True
    elif set(database).issubset(known):
        state = "upgrade-required"
        compatible = True
    else:
        error = "database revision is not in the candidate image migration ancestry"

    return MigrationState(
        schema_version=1,
        airflow_version=airflow_version,
        database_dialect=database_dialect,
        database_heads=database,
        image_heads=image,
        state=state,
        compatible=compatible,
        error=error,
    )


def inspect_migration_state() -> MigrationState:
    """Read database heads and the candidate image's bundled Alembic graph."""
    from airflow import settings
    from airflow.migrations import __file__ as migrations_file
    from airflow.version import version as airflow_version
    from alembic.migration import MigrationContext
    from alembic.script import ScriptDirectory

    script = ScriptDirectory(str(Path(migrations_file).parent))
    image_heads = script.get_heads()
    image_revisions = [revision.revision for revision in script.walk_revisions()]
    engine = settings.get_engine()
    alembic_logger = logging.getLogger("alembic")
    previous_level = alembic_logger.level
    alembic_logger.setLevel(logging.WARNING)
    try:
        with engine.connect() as connection:
            database_heads = MigrationContext.configure(connection).get_current_heads()
    finally:
        alembic_logger.setLevel(previous_level)

    return assess_migration_heads(
        database_heads,
        image_heads,
        image_revisions,
        database_dialect=engine.dialect.name,
        airflow_version=airflow_version,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "current"))
    args = parser.parse_args(argv)

    state = inspect_migration_state()
    print(json.dumps(asdict(state), separators=(",", ":"), sort_keys=True))
    if not state.compatible:
        return 1
    if args.mode == "current" and state.state != "current":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
