# Airflow database migrations

Airflow metadata migrations are an explicit release step. Schedulers and API
servers only wait for the database to reach the image's migration head; they
never modify schema during boot. The candidate image is the sole source of
migration code.

Jarvis supports this workflow only with PostgreSQL. Airflow 3.3's migration
runner holds its database-wide `MIGRATIONS` advisory lock while Alembic applies
the graph, so concurrent operators or hosts cannot mutate the schema at the
same time. The migration service is behind Compose's `migration` profile and is
started only as a one-off command by `ctl migrate`.

## Compatibility contract

Before downtime, the candidate container reads the current Alembic heads and
compares them with the migration ancestry bundled in that exact image. It emits
one JSON object without the database URL or credentials:

```json
{"airflow_version":"3.3.2","compatible":true,"database_dialect":"postgresql","database_heads":["CURRENT"],"error":null,"image_heads":["TARGET"],"schema_version":1,"state":"upgrade-required"}
```

The states are:

- `current`: the database exactly matches the candidate image;
- `upgrade-required`: every database head is an ancestor of the candidate;
- `uninitialized`: the empty database can be initialized from migration files;
- `incompatible`: the database is newer, divergent, lacks a candidate head, or
  is not PostgreSQL.

An incompatible preflight leaves the existing control service running. Normal
`ctl deploy control` and `ctl deploy all` run the stricter `current` check using
a candidate tag file. They promote that file to the active tag only after the
check passes, so deployment cannot silently perform or skip a migration. A
successful migration also writes a private pending-release marker; deployment
must match it byte-for-byte and removes it only after activation succeeds.

## Release procedure

Build and publish one application tag before starting; `ctl` resolves and pins
its immutable registry digest. Confirm a successful backup and usable PITR
window, and record its provider identifier or change-ticket evidence. Production
requires that reference on the command line:

```bash
uv run ctl migrate --tag GIT_SHA --backup-reference BACKUP_OR_PITR_REFERENCE
```

The command performs this fixed sequence:

1. Copies only allowlisted non-secret runtime configuration and a separate
   migration tag to the control host.
2. Pulls the candidate image and runs compatibility preflight while the current
   control service remains available.
3. Stops the scheduler and API only after preflight succeeds and records the
   exact tag and digest as a pending migration release.
4. Runs `airflow db migrate --use-migration-files` with a 30-minute bound and
   Airflow's cross-host database advisory lock.
5. Checks all Airflow and external-provider migrations and emits final `current`
   JSON.
6. Leaves control stopped so an older image cannot write to the upgraded schema.

Immediately deploy the exact same tag and pass its health gate:

```bash
uv run ctl deploy all --tag GIT_SHA
```

Do not change tags between these commands. Preserve the preflight and final JSON,
backup reference, operator, timestamps, migration logs, deploy health result, and
synthetic DAG result as release evidence.

## Failure and rollback

If preflight fails, investigate the reported heads; the existing control service
continues running. Never force an unknown or newer revision through an older
image.

If migration fails after control stops, keep control stopped and preserve the
container and database logs. Do not repeatedly rerun a partially failed release
until the migration's transactional behavior and current heads are understood.
The pending marker intentionally remains. Removing it to resume the prior tag is
a recovery action that requires proving the database still matches that image.

The default rollback is database recovery, not an automatic Alembic downgrade:

1. Restore the recorded pre-migration backup/PITR point to a replacement
   PostgreSQL instance.
2. Validate its migration head and `airflow db check` from the prior image.
3. Update the database secret/reference through the approved secret-rotation
   path.
4. Record approval to remove `.env.migration-pending`; this is permitted only
   after the restored database has passed the prior image's compatibility check.
5. Deploy the prior immutable tag and run scheduler, API, remote-log, and
   synthetic-DAG checks.

Use `airflow db downgrade` only when the exact migration explicitly documents a
lossless downgrade and that path has passed the same staging fixture. Never
point the prior image at an upgraded production database merely because its
containers start.

## Required staging drill

Before the first production migration and after an Airflow minor-version change:

1. Restore a production-like backup into staging.
2. Run the candidate preflight and archive its JSON.
3. Start two migration commands and confirm the database lock serializes them.
4. Complete migration, deploy the exact candidate, and run a synthetic DAG.
5. Exercise the recovery procedure using the recorded pre-migration point.
6. Record downtime, migration duration, restored heads, data validation, and
   whether the provisional RTO/RPO targets were met.

Local tests validate orchestration and compatibility classification. A real
backup, private database, workload identity, concurrent-lock test, and rollback
drill remain required environment evidence.
