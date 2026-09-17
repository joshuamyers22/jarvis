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

Each module produces the same outputs, which is where the abstraction does
hold: `storage_uri`, `registry`, `batch_job_name`, `db_host`, and the identities
each role runs as. Feed those into `.env` and the rest of the platform does not
know or care which cloud it is on.

## AWS shared notebook storage

The AWS module optionally exposes a `notebook_efs` output. With
`enable_notebook_efs = true`, it creates encrypted, backed-up EFS storage and a
UID/GID 50000 access point. A second environment can pass the resulting file
system, access point, and mount-target security-group IDs to use the same files.

EFS is intentionally AWS-specific and does not alter the provider-neutral data
path: datasets and artifacts remain in object storage. See
[`docs/notebooks.md`](../docs/notebooks.md#shared-notebooks-on-amazon-efs) for the
mount, cross-environment, and recovery procedure.
