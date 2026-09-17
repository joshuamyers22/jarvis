# Cloud SQL production policy

Jarvis uses one private Cloud SQL for PostgreSQL 16 instance for Airflow
metadata. Terraform's `database_policy` output is the reviewable contract for
its availability, recovery, maintenance, and observability controls.

## Enforced baseline

| Control | Policy |
|---|---|
| Connectivity | Private IP only; public IPv4 disabled; encrypted connections required |
| Availability | Production is `REGIONAL`; development and staging remain `ZONAL` |
| Storage | SSD with automatic growth; Terraform ignores growth of the initial disk size so it never attempts a destructive shrink |
| Backups | Daily automated backups; retain eight so backup coverage exceeds the seven-day PITR-log window |
| PITR | Enabled with seven days of transaction logs; backup count must exceed log-retention days |
| Deletion | Protected environments enable both Terraform deletion protection and the Cloud SQL API deletion-protection flag |
| Maintenance | Development receives `canary`, staging `stable`, and production `week5` updates in explicit UTC windows |
| Query Insights | Enabled with five plans per minute, 1,024-byte query strings, and application tags; client addresses are not recorded |

Cloud SQL regional HA protects production from an instance or zonal failure; it
does not protect against a whole-region outage. A cross-region replica is out of
scope until the restore benchmark or business requirements show that a
two-hour regional recovery target cannot be met from backups.

## Recovery objectives

The initial production objectives are:

- RPO: five minutes or better through point-in-time recovery.
- RTO: two hours to create a recovery instance, validate Airflow metadata, and
  switch the control plane.

These are provisional engineering targets, not validated service levels. The
`database_policy.recovery_objectives.status` output remains
`p2.5-automation-ready-live-evidence-required` until the first scheduled or
manual staging drill passes. The automated benchmark records the source and
target instances, requested recovery timestamp, measured RPO/RTO, validation
queries, Airflow smoke-test result, operator, ticket, and cleanup evidence. See
the [recovery-drill runbook](recovery-drills.md). If the measured
RPO or RTO misses its target, do not relabel it as met: either improve the restore
path or approve a cross-region disaster-recovery design.

## Apply and verify

Review a saved live-root plan before applying. Enabling PITR or changing Query
Insights query length can restart an existing instance, and enabling regional HA
reconfigures production, so schedule the first rollout in an approved window.

After apply, capture the Terraform policy and provider state without exporting
credentials:

```bash
scripts/gcp-live.sh prod output
gcloud sql instances describe research-prod-airflow \
  --project JARVIS_PROD_PROJECT \
  --format='yaml(settings.availabilityType,settings.backupConfiguration,settings.ipConfiguration,settings.maintenanceWindow,settings.insightsConfig,settings.deletionProtectionEnabled)'
gcloud sql backups list \
  --instance research-prod-airflow \
  --project JARVIS_PROD_PROJECT
```

Verify that the latest automated backup succeeded and that the earliest
restorable PITR timestamp covers the expected seven-day window. Run or inspect
the quarterly P2.5 recovery evidence; neither a successful Terraform apply nor a
listed backup proves restorability.

## Maintenance rollout

Development receives updates first, staging second, and production in the
five-week track. For a notified maintenance release:

1. Exercise scheduler and database smoke tests in development after its window.
2. Repeat in staging and stop promotion on migration, connection, or performance
   regressions.
3. Confirm a current successful production backup before the production window.
4. After maintenance, verify Cloud SQL health, Airflow scheduler heartbeats,
   database migrations, task-log delivery, and one synthetic DAG.

Do not disable either production deletion-protection layer as routine cleanup.
An approved break-glass change must first capture a successful backup and restore
evidence, identify the exact instance, obtain two-person review, and apply the
protection-removal change separately from deletion.

## References

- [Cloud SQL high availability](https://cloud.google.com/sql/docs/postgres/high-availability)
- [Cloud SQL backup options and retention](https://cloud.google.com/sql/docs/postgres/backup-recovery/backup-options)
- [Cloud SQL point-in-time recovery](https://cloud.google.com/sql/docs/postgres/backup-recovery/pitr)
- [Terraform Google SQL instance resource](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/sql_database_instance)
