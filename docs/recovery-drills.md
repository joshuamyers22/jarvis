# Recovery drills

P2.5 turns backup configuration into a quarterly, evidenced restore exercise.
The supported production path is GCP-first, and every automated drill runs in
the staging project. The runner refuses projects that do not end in `-dev` or
`-stage`; Terraform creates no recovery trust or permissions in production.

## Recovery contract

Each run performs four independent exercises:

| Exercise | Isolated target | Validation | Cleanup |
|---|---|---|---|
| Cloud SQL PITR | New `recovery-drill-*-sql` clone at five minutes before drill start | Instance is `RUNNABLE` with one private IP; from the private control VM, SQL reads Airflow migration and row metadata and `airflow db check` passes | Delete clone |
| Object version | Unique `recovery-drills/DRILL_ID/object.txt` canary | Overwrite, copy the original generation back with a generation-match precondition, and compare SHA-256 | Delete every canary generation by exact generation number |
| Terraform state | Copy one noncurrent `environments/stage/default.tfstate` generation to an isolated `recovery-drills/` key | Parse in memory and verify Terraform state version, lineage, serial, and resource structure; state content is not included in evidence | Delete isolated copy by exact generation number |
| Notebook volume | On-demand snapshot of the stopped notebook data disk, a new temporary disk, and an isolated private replacement VM | Snapshot policy is attached; restored disk is `READY`, points to the expected snapshot, is not smaller than its source, and the replacement host mounts ext4 with the preserved filesystem-UUID marker | Delete replacement VM, restored disk, and drill snapshot |

The Cloud SQL objective is RPO ≤ 300 seconds and RTO ≤ 7,200 seconds. A
successful clone at the requested timestamp demonstrates that the transaction
logs cover the target RPO. RTO runs from the clone request through SQL and
Airflow validation. A result outside either bound fails the drill; do not edit
evidence to relabel it as successful.

Notebook files live on the independent `research-ENV-notebooks` persistent disk.
Terraform attaches a daily snapshot schedule with 14-day retention and keeps
automatic snapshots after source-disk deletion. The drill requires the notebook
VM to be stopped so the snapshot is filesystem-consistent. It creates a
temporary VM from the same exact host image with no service account or external
IP, attaches the restored disk, and reads the baked mount verifier's status over
IAP. A disk that exists but cannot be mounted is a failed restore.

## Identity and access

Non-production environments create `research-ENV-recovery`. It receives:

- Cloud SQL administration needed to clone and remove the temporary instance;
- Compute Instance Admin, OS Login, and IAP tunnel access needed to restore a
  disk, create the identity-free replacement host, and run private validation;
- `actAs` on the control service account only;
- object administration conditioned to the data bucket's `recovery-drills/`
  prefix; and
- create-only access to the backup bucket for immutable evidence.

It cannot read ordinary research objects, cannot impersonate job, feed,
notebook, CI, or deployer identities, and receives no production IAM binding.
The bootstrap state bucket is intentionally owned by a different Terraform
root. After applying staging, add the emitted recovery service account to the
bootstrap stack's `state_recovery_principals`, review that separate plan, and
apply it. This grants bucket-wide object metadata listing (Cloud Storage cannot
prefix-condition list permission), conditional read of only the staging state
object, and conditional mutation only under `recovery-drills/`. Never add the
identity to `state_writer_principals` or grant bucket administration.

GitHub federation reuses staging's repository ID, protected environment, and
`main`-ref boundary. Configure these non-secret variables on the protected
`staging` GitHub environment:

| Variable | Value |
|---|---|
| `GCP_RECOVERY_PROJECT_ID` | Dedicated project ending in `-stage` |
| `GCP_RECOVERY_REGION` / `GCP_RECOVERY_ZONE` | Staging region and zone |
| `GCP_RECOVERY_DATA_BUCKET` | Staging data bucket |
| `GCP_RECOVERY_BACKUP_BUCKET` | Staging backup bucket |
| `GCP_RECOVERY_STATE_BUCKET` | Versioned bootstrap state bucket |
| `GCP_RECOVERY_WIF_PROVIDER` | Staging `github_oidc.workload_identity_provider` output |
| `GCP_RECOVERY_SERVICE_ACCOUNT` | Staging `recovery_contract.service_account` output |
| `GCP_RECOVERY_IMAGE` | Image repository without a tag; the workflow appends the current main SHA |

The workflow uses keyless OIDC. Do not add a service-account key or database
password as a GitHub secret.

## Plan and execute

Inspect the Terraform contract first:

```bash
scripts/gcp-live.sh stage output
```

Preview the exact boundaries without cloud mutations:

```bash
uv run python scripts/gcp-recovery-drill.py plan \
  --project PROJECT-stage \
  --region us-central1 \
  --zone us-central1-a \
  --data-bucket STAGE_DATA_BUCKET \
  --backup-bucket STAGE_BACKUP_BUCKET \
  --state-bucket STATE_BUCKET \
  --state-prefix environments/stage \
  --image REGISTRY/IMAGE:GIT_SHA \
  --operator USER_OR_AUTOMATION \
  --ticket RECOVERY-123
```

Run manually only after reviewing that plan. The repeated project value is an
intentional destructive-operation guard:

```bash
uv run python scripts/gcp-recovery-drill.py run \
  --project PROJECT-stage \
  --region us-central1 \
  --zone us-central1-a \
  --data-bucket STAGE_DATA_BUCKET \
  --backup-bucket STAGE_BACKUP_BUCKET \
  --state-bucket STATE_BUCKET \
  --state-prefix environments/stage \
  --image REGISTRY/IMAGE:GIT_SHA \
  --operator USER_OR_AUTOMATION \
  --ticket RECOVERY-123 \
  --confirm-project PROJECT-stage
```

The scheduled workflow runs at 13:17 UTC on the first day of January, April,
July, and October. A concurrent run is never cancelled because interruption can
strand temporary resources. The job has a three-hour ceiling, uploads a 90-day
GitHub artifact, and writes the authoritative evidence to the staging backup
bucket.

## Evidence and incident handling

Local evidence is written under ignored `recovery-evidence/`; the durable copy
is `gs://STAGE_BACKUP_BUCKET/recovery-drills/DRILL_ID/evidence.json`. It records:

- source and isolated target identifiers, restored filesystem UUID, and
  replacement-host mount result;
- requested recovery time and measured RPO/RTO;
- SQL, Airflow, checksum, state-structure, and disk-source validation results;
- operator, ticket, start/finish times, and per-step duration; and
- cleanup status for every temporary resource.

Evidence contains identifiers and counts, never database URLs, state contents,
credential values, or command stderr. Failed preflight stops every cloud
mutation and produces local evidence only. Other failures still attempt cleanup
and make the workflow fail.

For any failed drill:

1. Open an incident linked to its evidence URI and preserve the GitHub logs.
2. Confirm cleanup; manually remove only resources carrying the exact drill ID.
3. Treat an RPO or RTO miss as an unmet objective, not a flaky test.
4. Correct the backup, network, identity, or validation path and rerun manually.
5. Require one passing rerun before closing the incident.

The first live staging run is the production-readiness acceptance event. Until
its `status` is `passed`, the recovery objectives remain provisional even though
the automation and backup controls are installed.

## References

- [Cloud SQL point-in-time recovery](https://cloud.google.com/sql/docs/postgres/backup-recovery/pitr)
- [Cloud Storage version recovery](https://cloud.google.com/storage/docs/using-versioned-objects)
- [Compute Engine snapshot restoration](https://cloud.google.com/compute/docs/disks/restore-snapshot)
- [Terraform GCS backend recovery recommendation](https://developer.hashicorp.com/terraform/language/backend/gcs)
