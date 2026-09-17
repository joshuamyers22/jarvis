# Storage classes and access boundaries

P2.1 separates durable data, Airflow logs, temporary scratch space, and backup
artifacts. The existing data bucket/container remains the canonical data
location, so adopting this contract does not rename or replace research data.
The other three locations are new.

## Contract

| Location | Contents | Runtime access | Versioning baseline |
|---|---|---|---|
| `data` | Raw, derived, and published artifacts | Job writes; feed ingests; notebook reads | Enabled on GCP/AWS; unsupported on Azure HNS |
| `airflow_logs` | Remote task logs only | Control writes and reads | Disabled |
| `scratch` | Disposable job and notebook intermediates | Job and notebook read/write | Disabled |
| `backup` | Recovery exports and restore artifacts | No runtime access | Enabled on GCP/AWS; unsupported on Azure HNS |

Every location is private and encrypted by its provider. GCP uses four buckets,
AWS uses four S3 buckets, and Azure uses four private containers in one ADLS
Gen2 hierarchical-namespace account. Azure HNS does not support blob versioning;
30-day blob/directory and container soft-delete policies provide delete recovery
but do not protect overwrites. Azure control-plane access uses the Container Instances
Contributor role instead of general resource-group Contributor, preventing the
control identity from using broad storage-management permissions to bypass the
container data-plane assignments. Provider-specific IAM remains resource-scoped:

AWS assigns a separate customer-managed, automatically rotating KMS key to each
storage class; its runtime roles receive key permissions only for the classes
they can access. Azure Storage and Key Vault deny public data-plane traffic and
admit only the configured VM and ACI subnets through service endpoints. GCP
Cloud SQL accepts encrypted connections only.

- the control identity has object access only to `airflow_logs`;
- the job identity can write `data` and `scratch`;
- the feed identity can ingest into `data` but has no log, scratch, or backup
  access;
- the notebook identity reads `data` and writes `scratch`; and
- no runtime identity can access `backup`.

The dedicated non-production recovery automation identity is not a runtime
workload. It has create-only access to append immutable drill evidence to the
backup bucket; it cannot read or replace evidence. Production creates no such
binding.

The GCP feed grant is create-only. AWS `PutObject` and Azure Blob Data
Contributor do not provide the same no-overwrite guarantee by themselves;
vendor key design must therefore use immutable object names and completion
markers rather than relying on provider IAM to prevent overwrite.

## Approved lifecycle policy

Lifecycle policy version 1 applies the same intent to every environment and
provider:

| Boundary | Approved behavior | Safety property |
|---|---|---|
| Current raw data | Transition `raw/` objects after 90 days (GCP Coldline, AWS Glacier Instant Retrieval, Azure Cool) | Never delete current raw objects; raw remains the replay source of truth |
| Noncurrent data versions | On GCP/AWS, retain the newest three and keep versions for at least 30 days before pruning | A bad overwrite has both a count-based and time-based recovery window |
| Airflow logs | Apply lifecycle deletion after 90 days | Operational logs do not become an unbounded archive |
| Scratch | Apply lifecycle deletion after 14 days | Temporary output cannot silently become durable storage |
| Backup | No automatic deletion in this phase | Backup retention changes only with the restore policy in P2.5 |

GCP and AWS enforce both the newest-three count and 30-day minimum age for
noncurrent data versions. Azure Blob versioning is unsupported on the selected
hierarchical-namespace account. Azure instead enables 30-day blob/directory and
container soft delete, reports `unsupported-on-hierarchical-namespace` in
`storage_lifecycle_policy`, and does not claim overwrite recovery. Azure does not
qualify for production parity until the design adds a supported immutable-copy or
snapshot mechanism and exercises it. The log and scratch lifecycle actions occur
after 90 and 14 days, after which Azure's soft-delete recovery window still applies.

The Terraform output `storage_lifecycle_policy` is the reviewable contract for
the effective transition, expiry, version-recovery, and provider-limitation
settings. Plans that reduce a recovery window or introduce deletion for current
data or backups require an explicit exception rather than an unreviewed variable
override.

### Exceptions

An exception is allowed only for a legal hold, a vendor contract, or a documented
reproducibility requirement. The approving pull request must record the affected
environment and prefix, owner, reason, approval or ticket ID, requested policy,
review date, and removal or renewal condition. Prefer a narrower prefix-specific
rule over changing the environment-wide baseline. Legal holds take precedence
over expiry; objects under hold must be isolated from the standard destructive
rule and included in recovery testing. Cost preference alone is not an exception.

Terraform exposes the same provider-neutral outputs from every module:

- `storage_uri` remains the canonical data URI for compatibility;
- `airflow_logs_uri`, `scratch_uri`, and `backup_uri` identify the other
  locations;
- `storage_locations` is the four-URI deployment map;
- `storage_contract` records versioning and effective workload access; and
- `storage_lifecycle_policy` records effective retention and provider limitations.

Runtime configuration maps `storage_uri` to `RP_STORAGE_URI`, `scratch_uri` to
`RP_SCRATCH_URI`, and `airflow_logs_uri` to `AIRFLOW_REMOTE_LOGS`. Backup
automation consumes `backup_uri` only for P2.5 evidence; do not attach a runtime
identity as a shortcut.

## Data ownership

The physical storage and lifecycle settings on this page are paired with the
[data ownership contract](data-ownership.md). Its source is the editable,
provider-neutral [`config/data-ownership.toml`](../config/data-ownership.toml)
manifest. It assigns raw, derived, artifact, scratch, quarantine, log, and
backup boundaries to accountable groups; records readers, writers, retention,
and recovery expectations; and keeps human ownership separate from cloud
workload identities.

Group IDs are stable logical roles rather than hard-coded people or provider
accounts. A deployment can map them to its own GitHub teams, directory groups,
or ticket queues by changing the group registry and class assignments. Run
`make ownership-render` after changes and `make ownership-check` before review.
Changes to readers, writers, locations, or prefixes also require a matching IAM
change; editing the ownership manifest never grants cloud access by itself.

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
file; each value must be a globally unique S3 bucket name. It also requires
`workload_egress_cidr_blocks`, restricted to approved private endpoints or an
egress proxy—unrestricted public routes are rejected. Azure defaults to
`research`, `airflow-logs`, `scratch`, and `backups` within the environment's
storage account and exposes variables to change any container name. Its VM and
ACI subnets must have Storage and Key Vault service endpoints. Keep all four
names distinct on every provider.

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

Also capture `terraform output -json storage_lifecycle_policy`, upload a test
object and a replacement version, and verify the provider reports the expected
transition/expiry rules before removing any superseded policy. Lifecycle actions
are asynchronous; configuration acceptance is not evidence that an object was
actually transitioned or deleted.

Do not place credentials, Terraform state, or notebook home directories in any
of these object-storage locations. State retains its bootstrap bucket, and
notebook persistence follows the separate volume/EFS procedure.

## References

- [Cloud Storage IAM roles](https://cloud.google.com/storage/docs/access-control/iam-roles)
- [Blocking public access to Amazon S3 storage](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html)
- [Azure built-in roles for containers](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles/containers)
- [Azure Blob versioning support](https://learn.microsoft.com/azure/storage/blobs/versioning-overview)
- [Azure soft delete with hierarchical namespaces](https://learn.microsoft.com/azure/storage/blobs/soft-delete-blob-overview)
