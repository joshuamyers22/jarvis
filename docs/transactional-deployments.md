# Transactional deployments and rollback

Jarvis deploys an application release as a Git tag plus its registry-resolved
`sha256` manifest digest. The tag is retained for humans; Compose, Cloud Run,
and AWS Batch receive the exact `repository:tag@sha256:...` reference. A moved
tag therefore cannot change a running or rolled-back release.

P3.4 supplies four inspection and recovery commands:

```bash
uv run ctl plan all --tag GIT_SHA
uv run ctl status all
uv run ctl doctor all
uv run ctl rollback all --yes
```

`plan` resolves the registry digest and compares it with every host without
changing a service. `status` returns JSON containing the configured digest,
the image reference resolved by Compose, health, and the previous release.
`doctor` additionally checks environment requirements, database compatibility,
remote log access, and evidence from the accepted release. These commands
return non-zero when a required check fails, so operators and automation can
use them as gates.

## Deploy transaction

Build and push the image before planning or deploying. If the release contains
an Airflow migration, complete the migration workflow first; `migrate` now
pins the same registry digest as `deploy`.

```bash
uv run ctl plan all --tag GIT_SHA
uv run ctl migrate --tag GIT_SHA --backup-reference BACKUP_OR_PITR_EVIDENCE
uv run ctl deploy all --tag GIT_SHA
uv run ctl status all
uv run ctl doctor all
```

For each host, `deploy` performs these gates in order:

1. resolve the tag once to a valid registry digest;
2. copy only allowlisted non-secret runtime configuration and stage a candidate
   release file;
3. pull the exact digest and verify the image's baked `RP_IMAGE_CLOUD` label
   against the target provider;
4. for control, verify the candidate migration graph matches the live schema;
5. keep candidate Compose/runtime files separate, save the active release and
   its files in the previous slot, and promote the candidate files;
6. activate the systemd/Compose service and wait for health;
7. prove that remote service logs are retrievable;
8. point the batch definition at the same digest and run `release-probe`;
9. write release evidence only after the probe writes and reads its scratch
   object and `_SUCCESS` marker.

Production control deploys cannot disable the batch update or synthetic probe.
The probe uses the job workload identity and the environment's scratch storage;
it neither calls a market-data vendor nor modifies durable research datasets.

If a host health or log gate fails, the CLI prints the last 200 service log
lines and swaps back to the previous release. If any later host, batch update,
or synthetic probe fails, it rolls every already-activated role back in reverse
order and restores the prior batch image. Control rollback runs the old image's
schema compatibility check before its tag is promoted. An incompatible old
image remains stopped: restore the database using the migration runbook rather
than forcing an unsafe downgrade.

The first-ever transactional deployment has no previous digest. If it fails,
the affected service is stopped instead of left on an unverified candidate.
Establish and validate the initial release in staging before the first
production transaction.

## Explicit rollback

`rollback` requires `--yes`, preflights every previous digest before changing
services, then health-gates hosts, batch, and synthetic storage output. An
`all` rollback refuses to proceed when roles do not share one previous release;
roll back those roles individually after investigating the drift.

```bash
time uv run ctl rollback all --yes
uv run ctl status all
uv run ctl doctor all
```

The active and previous slots swap after a successful rollback, so the original
release remains available for a controlled roll-forward. A failed rollback
attempt restores the original release and reports any host requiring manual
operator action.

## Staging drill and evidence

Before production use, run the following in staging and retain the command
output, release IDs, health JSON, service journal excerpts, batch execution,
and scratch marker URI:

1. Deploy a known-good release to all roles and run `doctor`.
2. Deploy a candidate with a deliberately failing health check.
3. Confirm the CLI emits failure logs and the known-good digest remains active.
4. Deploy a valid successor and confirm one release ID is recorded by all roles.
5. Run `time ctl rollback all --yes`; confirm the prior compatible digest is
   healthy within the 15-minute recovery target.
6. Run `doctor` and confirm schema, logs, image references, and release evidence.

Do not inject a deliberate health failure in production. Repeat the safe
rollback exercise after material supervisor, Compose, database, or batch changes.
