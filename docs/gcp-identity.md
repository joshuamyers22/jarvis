# GCP identity and GitHub federation

Jarvis uses six user-managed service accounts in every GCP environment. Compute
Engine and Cloud Run workloads never use a Google-managed default service
account, and no service-account key is created.

| Identity | Purpose | Effective access |
|---|---|---|
| `research-ENV-deployer` | Terraform plans and applies | Reviewed infrastructure-admin roles; may attach the four runtime identities |
| `research-ENV-ci` | GitHub Actions image publishing | Artifact Registry writer on the `research` repository only |
| `research-ENV-control` | Airflow scheduler and API | Execute the one Cloud Run job with per-task overrides, Cloud SQL client, log-object administration, its database secret, image pull |
| `research-ENV-job` | Cloud Run batch execution | Data and scratch object administration; image pull |
| `research-ENV-feed` | Append-only feed ingestion | Object creation and image pull; no read, overwrite, or delete |
| `research-ENV-notebook` | Interactive research | Data-object read, scratch-object administration, and image pull |
| Named operator users/groups | Human VM operations | OS Login, IAP tunnels restricted to port 22, instance start/stop, and actAs only on the three VM identities |

Terraform's native policy tests assert the exact account set, workload
attachments, project and resource roles, GitHub trust condition, and forbidden
broad roles. They run in CI without cloud credentials.

## Initial identity handoff

The deployer account cannot create itself. Perform this one-time sequence with a
named bootstrap administrator:

1. Copy the appropriate `.env.live.example`, fill every placeholder, and keep
   both impersonation variables commented out.
2. Obtain immutable GitHub IDs without storing a token in the env file:

   ```bash
   gh api repos/OWNER/REPOSITORY \
     --jq '{repository_id: (.id|tostring), owner_id: (.owner.id|tostring)}'
   ```

3. Set `TF_VAR_deployer_principals` and `TF_VAR_operator_principals` to named IAM
   members. Prefer managed groups, for example `['group:platform@example.com']`;
   never use `allUsers` or `allAuthenticatedUsers`. Operator users must belong
   to the same Google organization unless an organization administrator also
   grants `roles/compute.osLoginExternalUser`.
4. Run `scripts/gcp-live.sh ENV plan` and `apply` as the bootstrap administrator.
5. Add `serviceAccount:research-ENV-deployer@PROJECT_ID.iam.gserviceaccount.com`
   to the state bootstrap stack's `state_writer_principals`, review, and apply that
   change.
6. Uncomment `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` and
   `GOOGLE_BACKEND_IMPERSONATE_SERVICE_ACCOUNT` in `.env.live`. All subsequent
   live-root operations use short-lived deployer credentials.

The deployer is privileged by design. Grant impersonation only to a named group
or emergency automation principal, review the membership independently, and do
not grant it to GitHub CI.

Operator access is deliberately separate. Operators receive no Compute Admin
role: a small project custom role permits only instance start/stop, while OS
Login and a port-22 IAM condition constrain SSH through IAP. Because an SSH
session can use the VM's metadata-server identity, OS Login also requires
`roles/iam.serviceAccountUser` on the attached control, feed, and notebook
accounts. Jarvis grants that role on those three accounts only. Google documents
these requirements in its [OS Login setup guide](https://cloud.google.com/compute/docs/oslogin/set-up-oslogin).

## GitHub Actions trust boundary

Each environment owns a separate Workload Identity Pool and provider. Admission
requires all of the following claims to match:

- the exact `owner/repository` name;
- the immutable numeric repository and owner IDs;
- the GitHub environment (`development`, `staging`, or `production`); and
- `refs/heads/main`.

The service-account binding additionally selects the immutable repository ID.
Using numeric IDs prevents a deleted or renamed account from being impersonated
by someone who later claims the old name. Google also requires a provider
attribute condition for shared issuers such as GitHub. See Google's
[deployment-pipeline federation guide](https://cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines)
and GitHub's [OIDC claim reference](https://docs.github.com/en/actions/reference/security/oidc).

Create the `production` GitHub environment before enabling publishing. Restrict
it to `main`, require reviewers, prevent self-review, and define these environment
variables from the production Terraform outputs:

| GitHub environment variable | Value |
|---|---|
| `GCP_PROJECT_ID` | Production project ID |
| `GCP_IMAGE` | `REGION-docker.pkg.dev/PROJECT_ID/research/base` |
| `GCP_WIF_PROVIDER` | `github_oidc.workload_identity_provider` |
| `GCP_CI_SERVICE_ACCOUNT` | `github_oidc.ci_service_account` |

These are identifiers, not credentials, so repository/environment variables are
appropriate. The workflow requests `id-token: write` and exchanges the GitHub
OIDC token for short-lived Google credentials. Do not create a JSON key or store
one as a GitHub secret. The current workflow publishes only through the protected
`production` environment; add dedicated protected jobs before using the dev or
staging providers.

After apply, verify the configured values with:

```bash
scripts/gcp-live.sh prod output
terraform -chdir=terraform/gcp test
```
