# Storage classes and access boundaries

P2.1 separates durable data, Airflow logs, temporary scratch space, and backup
artifacts. The existing data bucket/container remains the canonical data
location, so adopting this contract does not rename or replace research data.
The other three locations are new.

## Contract

| Location | Contents | Runtime access | Versioning baseline |
|---|---|---|---|
| `data` | Raw, derived, and published artifacts | Job writes; feed ingests; notebook reads | Enabled |
| `airflow_logs` | Remote task logs only | Control writes and reads | Disabled on GCP/AWS; account-level on Azure |
| `scratch` | Disposable job and notebook intermediates | Job and notebook read/write | Disabled on GCP/AWS; account-level on Azure |
| `backup` | Recovery exports and restore artifacts | No runtime access | Enabled |

Every location is private and encrypted by its provider. GCP uses four buckets,
AWS uses four S3 buckets, and Azure uses four private containers in one ADLS
Gen2 account. Azure versioning is an account-level setting and therefore covers
all four containers. Azure control-plane access uses the Container Instances
Contributor role instead of general resource-group Contributor, preventing the
control identity from using broad storage-management permissions to bypass the
container data-plane assignments. Provider-specific IAM remains resource-scoped:

- the control identity has object access only to `airflow_logs`;
- the job identity can write `data` and `scratch`;
- the feed identity can ingest into `data` but has no log, scratch, or backup
  access;
- the notebook identity reads `data` and writes `scratch`; and
- no runtime identity can access `backup`.

The GCP feed grant is create-only. AWS `PutObject` and Azure Blob Data
Contributor do not provide the same no-overwrite guarantee by themselves;
vendor key design and the P2.2 retention/immutability decision must account for
that provider difference.

Terraform exposes the same provider-neutral outputs from every module:

- `storage_uri` remains the canonical data URI for compatibility;
- `airflow_logs_uri`, `scratch_uri`, and `backup_uri` identify the other
  locations;
- `storage_locations` is the four-URI deployment map; and
- `storage_contract` records versioning and effective workload access.

Runtime configuration maps `storage_uri` to `RP_STORAGE_URI`, `scratch_uri` to
`RP_SCRATCH_URI`, and `airflow_logs_uri` to `AIRFLOW_REMOTE_LOGS`. Backup
automation will consume `backup_uri` in P2.3/P2.5; do not attach a runtime
identity as a shortcut.

## Provider inputs

Each GCP live env file must provide four globally unique bucket names:

```bash
TF_VAR_bucket_name=jarvis-ENV-data
TF_VAR_airflow_log_bucket_name=jarvis-ENV-airflow-logs
TF_VAR_scratch_bucket_name=jarvis-ENV-scratch
TF_VAR_backup_bucket_name=jarvis-ENV-backup
```

The helper rejects missing placeholders, and Terraform rejects duplicate or
invalid names. All GCP buckets enforce uniform bucket-level access,
public-access prevention, and `force_destroy = false`.

The AWS root requires the same four variable names in its private variable
file; each value must be a globally unique S3 bucket name. Azure defaults to
`research`, `airflow-logs`, `scratch`, and `backups` within the environment's
storage account and exposes variables to change any container name. Keep all
four names distinct on every provider.

## Existing-environment migration

Review the plan before changing runtime configuration. It must retain the
existing data resource address and show three new storage locations; replacement
of the data bucket/account/container is not an acceptable P2.1 change.

If Airflow already has logs under the old data location:

1. Create the new log location with a reviewed staged Terraform apply.
2. Copy the historical log objects with a named migration principal and verify
   object counts and representative reads.
3. Set `AIRFLOW_REMOTE_LOGS` to the `airflow_logs_uri`, restart control services,
   and verify a new task log is readable.
4. Complete the Terraform apply that removes control access from the data
   location.
5. Retain or remove the old prefix only under the approved P2.2 lifecycle
   policy; do not delete it as part of this infrastructure migration.

For a new environment, apply all four locations together and populate runtime
configuration directly from `storage_locations`.

## Verification

After apply, capture `terraform output -json storage_contract` and verify:

- all four URIs are distinct and environment-local;
- public access is blocked;
- job and notebook can create and remove a scratch test object;
- notebook can read but cannot modify a data test object;
- control can write logs but cannot read data or scratch; and
- every runtime identity is denied access to the backup location.

Do not place credentials, Terraform state, or notebook home directories in any
of these object-storage locations. State retains its bootstrap bucket, and
notebook persistence follows the separate volume/EFS procedure.

## References

- [Cloud Storage IAM roles](https://cloud.google.com/storage/docs/access-control/iam-roles)
- [Blocking public access to Amazon S3 storage](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html)
- [Azure built-in roles for containers](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles/containers)
