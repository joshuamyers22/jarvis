# Terraform

**Three parallel modules, not one parameterized module.** This is deliberate and
it is the honest boundary of the abstraction in this project.

The runtime abstracts cleanly: `jobs/`, `dags/` and `compose/` contain no
provider branch, because storage goes through fsspec and dispatch goes through
one function per cloud. Infrastructure does not abstract cleanly. IAM,
networking and workload identity are not the same shapes with different names --
they are different models:

| Concern | GCP | AWS | Azure |
|---|---|---|---|
| Workload identity | Service account attached to instance | IAM role via instance profile | Managed identity |
| Grant scope | Per-resource IAM binding | Policy document attached to role | Role assignment at a scope |
| Batch unit | Cloud Run Job (mutable) | Batch job definition (immutable revisions) | Container Instance (ephemeral, no definition) |
| Private DB access | Private Service Connect | VPC subnet + security group | Private endpoint / VNet delegation |
| SSH without public IP | IAP tunnel | SSM Session Manager | Bastion |

A single module covering all three would be a wrapper around `count` and
conditional resources that nobody can read and Terraform cannot plan cleanly.
Three modules are more lines and less complexity.

AWS and Azure remain directly deployable provider roots:

```bash
cd terraform/aws     # or azure
terraform init -backend-config="bucket=my-tfstate"
terraform apply -var-file=prod.tfvars
```

The AWS root requires `workload_egress_cidr_blocks` to contain only reviewed
private-endpoint or egress-proxy CIDRs; unrestricted `0.0.0.0/0` and `::/0`
routes are rejected. The Azure VM and ACI subnets must expose the
`Microsoft.Storage` and `Microsoft.KeyVault` service endpoints because both
data planes default to deny.

For GCP, create the protected remote-state bucket with the standalone
[`bootstrap/gcp`](bootstrap/gcp/README.md) root, then deploy only through the
explicit [`live/gcp/{dev,stage,prod}`](live/gcp/README.md) roots. `terraform/gcp`
is their reusable platform child module and `terraform/gcp/network` supplies the
managed private-network boundary; neither child module should be applied directly.
The platform module creates user-managed identities and GitHub federation; see
the [GCP identity runbook](../docs/gcp-identity.md) for the one-time handoff.
Its APIs, audit logs, budget, quota alerts, deletion policy, and external
organization requirements are documented in the
[GCP guardrail runbook](../docs/gcp-guardrails.md).
Cross-project buckets and BigQuery datasets remain denied by default and are
declared through the reviewed, resource-scoped contract in the
[GCP data-access runbook](../docs/gcp-data-access.md).
The control, feed, and notebook instances accept only exact versioned GCE image
references; build and replace them with the
[GCP host-image runbook](../docs/host-images.md).

Each module produces the same outputs, which is where the abstraction does
hold: `storage_uri`, `storage_locations`, `storage_contract`,
`storage_lifecycle_policy`, `registry`,
`batch_job_name`, `db_host`, and the identities each role runs as. GCP also
emits `database_policy` as its explicit Cloud SQL availability and recovery
contract and `runtime_secret_contract` as its non-secret secret-ID/IAM contract;
see the [Cloud SQL runbook](../docs/cloud-sql.md) and
[runtime-secrets runbook](../docs/runtime-secrets.md). The GCP
`recovery_contract` exposes the non-production drill identity, notebook snapshot
policy, evidence prefixes, and RPO/RTO boundaries described in the
[recovery-drill runbook](../docs/recovery-drills.md). Data, Airflow
logs, scratch, and backups use distinct resource-level boundaries; see the
[storage-class runbook](../docs/storage-classes.md). Feed only non-secret outputs
and secret identifiers into `.env`; values remain in the provider store and are
resolved through attached identity.

## AWS shared notebook storage

The AWS module optionally exposes a `notebook_efs` output. With
`enable_notebook_efs = true`, it creates encrypted, backed-up EFS storage and a
UID/GID 50000 access point. A second environment can pass the resulting file
system, access point, and mount-target security-group IDs to use the same files.

EFS is intentionally AWS-specific and does not alter the provider-neutral data
path: datasets and artifacts remain in object storage. See
[`docs/notebooks.md`](../docs/notebooks.md#shared-notebooks-on-amazon-efs) for the
mount, cross-environment, and recovery procedure.
