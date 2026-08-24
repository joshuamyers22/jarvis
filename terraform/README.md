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

Pick one:

```bash
cd terraform/gcp     # or aws, or azure
terraform init -backend-config="bucket=my-tfstate"
terraform apply -var-file=prod.tfvars
```

Each module produces the same outputs, which is where the abstraction does
hold: `storage_uri`, `registry`, `batch_job_name`, `db_host`, and the identities
each role runs as. Feed those into `.env` and the rest of the platform does not
know or care which cloud it is on.
