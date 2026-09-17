# GCP cross-project data access

P1.6 adopts an explicit, default-deny contract for data outside a Jarvis
environment project. The currently approved set is empty in `dev`, `stage`, and
`prod`. An environment creates no cross-project grant until its private env file
declares a reviewed Cloud Storage bucket or BigQuery dataset.

Access is resource-scoped. Jarvis does not use project allowlists in Python,
project-level data roles in source projects, shared service accounts, or basic
Owner/Editor roles. A dedicated bucket or dataset is the security boundary; a
Cloud Storage object prefix is not treated as one.

## Workload policy

| Resource | Job | Feed | Notebook | Control / CI / deployer / operator |
|---|---|---|---|---|
| Cloud Storage | `reader` or `writer` | `creator` only | `reader` only | No grant |
| BigQuery dataset | `reader` or `writer` | No grant | `reader` only | No grant |

Storage maps `reader` to `roles/storage.objectViewer`, `creator` to
`roles/storage.objectCreator`, and `writer` to `roles/storage.objectUser`.
BigQuery maps `reader` to dataset-level `roles/bigquery.dataViewer` and `writer`
to dataset-level `roles/bigquery.dataEditor`. Workloads approved for a BigQuery
dataset also receive `roles/bigquery.jobUser` in their own Jarvis project—not in
the source project—so query execution and cost stay in the consumer boundary.

The feed role can append new objects but cannot read, overwrite, or delete them.
Notebook access remains read-only. Use the job identity for reviewed transforms
that must update shared data.

## Declaration and approval

Keep the two variables in every `.env.live` even when empty:

```bash
TF_VAR_shared_storage_buckets='{}'
TF_VAR_shared_bigquery_datasets='{}'
```

An approved storage declaration has this shape:

```bash
TF_VAR_shared_storage_buckets='{
  "shared-research-data": {
    "project_id": "shared-research-data",
    "source_environment": "shared",
    "location": "US",
    "owner": "group:data-owners@example.com",
    "classification": "confidential",
    "approval_id": "DATA-123",
    "review_on": "2026-12-31",
    "workload_access": {"job": "reader", "notebook": "reader"}
  }
}'
```

A BigQuery declaration is keyed by a stable local alias and additionally has a
`dataset_id`. The source environment must be `shared` or match the Jarvis root.
If a source project ID ends in `-dev`, `-stage`, or `-prod`, that suffix must
also match. Locations are limited to the root's region or its corresponding
multi-region (`us-central1` or `US` by default).

Every declaration must record:

- a source project and physical resource;
- a group-owned data owner, classification, approval/ticket ID, and next review
  date; and
- each eligible workload's exact access level.

Before approval, the source owner must confirm that a bucket uses uniform
bucket-level access and enforced public-access prevention, or that a dataset has
no `allUsers` or `allAuthenticatedUsers` access. Terraform checks these
properties and the declared project/location during planning.

## Apply authority

Terraform uses non-authoritative IAM member resources, preserving unrelated
source bindings. Managing a declaration still requires read and policy-update
permissions on that specific source bucket or dataset. Prefer one of these
handoffs:

1. The source data owner reviews and applies the environment plan.
2. The source owner grants the environment deployer a custom IAM role containing
   only the IAM-policy read/write permissions required for the named resource,
   scoped as narrowly as Google Cloud permits.

Do not grant Storage Admin, BigQuery Admin, Owner, or Editor across the source
project merely to make a Jarvis apply succeed. If the source team cannot
delegate narrow policy management, keep the Terraform declaration empty and
have that team manage the same explicit service-account member in its own state;
record that exception and independent drift evidence in the approval ticket.

## Review and revocation

At least quarterly, export `terraform output -json data_access_contract` and
have each recorded owner confirm the resource, classification, members, access
levels, and review date. A stale or unowned declaration fails governance review
even though the date is deliberately evidence rather than a clock-dependent
Terraform condition.

To revoke managed access, remove the declaration or workload entry, review the
plan, apply it, and verify the workload can no longer access the resource. Treat
copied or cached data separately: revoke derived copies, rotate exposed data or
credentials when appropriate, and retain audit evidence according to policy.

Application configuration should consume the approved resource names from
deployment configuration or Terraform outputs. Do not reproduce the project
list in Python; Terraform is the access inventory and IAM enforcement point.

## References

- [Cloud Storage IAM roles](https://cloud.google.com/storage/docs/access-control/iam-roles)
- [Cloud Storage IAM](https://cloud.google.com/storage/docs/access-control/iam)
- [BigQuery IAM roles](https://cloud.google.com/bigquery/docs/access-control)
- [Control access to BigQuery resources](https://cloud.google.com/bigquery/docs/control-access-to-resources-iam)
