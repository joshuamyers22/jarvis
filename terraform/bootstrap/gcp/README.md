# GCP Terraform-state bootstrap

This standalone root creates the GCS bucket used by Jarvis Terraform backends.
It deliberately does not create application infrastructure or GCP projects.
The target project must already exist, have billing enabled, and be controlled
by the platform administrators.

The bucket enforces uniform bucket-level access and public-access prevention,
retains noncurrent state generations for one year by default, enables object
versioning and soft-delete recovery, refuses force deletion, and is protected
from Terraform destroy. State clients receive object access only; the smaller
administrator set receives bucket-scoped administration.

## Prerequisites

- Terraform 1.13.3 and Google provider credentials through Application Default
  Credentials or service-account impersonation; do not download a JSON key.
- Temporary bootstrap permissions to enable the Cloud Storage API, create the
  bucket, and set its IAM policy in the existing project.
- Named state-writer and bucket-administrator principals. Do not use
  `allUsers`, `allAuthenticatedUsers`, or a shared user account.

## Environment and credentials

Bootstrap configuration is loaded from a private, ignored environment file:

```bash
cp terraform/bootstrap/gcp/.env.bootstrap.example \
  terraform/bootstrap/gcp/.env.bootstrap
chmod 600 terraform/bootstrap/gcp/.env.bootstrap
```

Replace every placeholder before running the helper. `TF_VAR_*` values supply
Terraform inputs. Authentication uses Application Default Credentials and,
preferably, `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT`; the same env file can later
reference a protected credential configuration through
`GOOGLE_APPLICATION_CREDENTIALS`. Never paste a JSON key into an env file or
commit the populated file.

## First apply

The GCS backend cannot be initialized until its bucket exists. The first apply
therefore uses local state, which must remain on an encrypted, access-controlled
workstation and must never be committed.

```bash
scripts/bootstrap-gcp-state.sh validate
scripts/bootstrap-gcp-state.sh bootstrap-plan
scripts/bootstrap-gcp-state.sh bootstrap-apply
```

Immediately migrate the bootstrap state into its reserved prefix:

```bash
scripts/bootstrap-gcp-state.sh migrate
```

The helper derives the non-secret backend bucket setting from the same env file.
After migration, use `scripts/bootstrap-gcp-state.sh plan` and `apply` for all
subsequent changes so Terraform never falls back to an empty local state.

## Environment backend allocation

Keep every root in its own prefix. The planned live roots use:

```text
bootstrap/gcp
environments/dev
environments/stage
environments/prod
```

Grant each environment deployer `roles/storage.objectAdmin` on this bucket only.
Bucket administrators retain `roles/storage.admin` on the bucket, not the
project. IAM changes may take several minutes to become effective.

## Retention and recovery

Do not add or lock a bucket-wide retention policy. Terraform's GCS backend uses
a temporary `.tflock` object for state locking and must delete it after every
operation; a minimum object-retention policy would prevent that deletion. The
bucket instead keeps noncurrent `.tfstate` generations for the configured
period and adds a soft-delete recovery window. Noncurrent `.tflock` generations
expire after one day because they contain no recoverable infrastructure state.

Recover an accidentally changed state by selecting a prior object generation in
Cloud Storage and restoring it as the live generation. Never use
`terraform state push -force` without first preserving the current remote state
and recording incident approval. Removing `prevent_destroy` or deleting this
bucket requires a separately reviewed break-glass change.
