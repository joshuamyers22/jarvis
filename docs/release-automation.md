# CI and release trust boundary

Jarvis separates unprivileged validation from registry mutation. Pull-request
code is never evaluated by a job that can request a cloud identity, enter a
GitHub environment, read a repository secret, log in to a registry, or push an
image.

## Workflow contract

| Workflow | Trigger | Authority | Result |
|---|---|---|---|
| `ci.yml` | Pull request and push to `main` | Read-only repository token; no environment, secret, or OIDC permission | Lint, types, ownership, unit/architecture/DAG tests, Terraform tests, Packer validation, security scans, image smoke tests, and validation SBOMs |
| `release.yml` | Successful completion of `ci` for a push to this repository's `main` branch | Read-only repository token plus OIDC inside the protected `production` environment | Immutable Git-SHA image publication for each configured provider |
| `recovery-drill.yml` | Schedule or explicit dispatch | Staging OIDC inside the protected `staging` environment | Isolated quarterly recovery evidence; never image publication |

The release workflow checks the CI conclusion, original event, branch, and
origin repository before its job can enter `production`. It checks out
`workflow_run.head_sha`, disables persisted checkout credentials, verifies that
exact 40-character commit locally, and tags the image with the same SHA.
Validation and release use separate BuildKit cache scopes so an untrusted pull
request cannot populate a cache consumed by a privileged build.

The repository policy tests reject a pull-request workflow containing any of
these capabilities:

- `id-token: write`;
- a GitHub environment or `secrets` context;
- a cloud authentication action;
- a registry login; or
- an image build with `push: true`.

The same tests require every third-party action in every workflow to use a full
commit SHA. Run them directly with:

```bash
uv run pytest -q tests/test_workflow_policy.py
```

## Required GitHub configuration

Apply an organization ruleset or branch protection rule to `main` that requires
a pull request, code-owner review for `.github/`, fresh approval after changes,
resolved conversations, and these successful CI jobs:

- `lint-and-test`;
- `terraform`;
- `host-image-template`;
- `security`; and
- every `image-test` matrix job.

Do not make the release workflow a merge check: it intentionally runs only
after the validated commit reaches `main`.

Configure the `production` environment with:

- deployment branches restricted to `main`;
- required release-manager review and prevention of self-review;
- administrator bypass disabled where the repository plan supports it; and
- no long-lived cloud credential secrets.

Provider identifiers belong in protected environment variables, not secrets:

| Provider | Environment variables |
|---|---|
| GCP | `GCP_IMAGE`, `GCP_PROJECT_ID`, `GCP_WIF_PROVIDER`, `GCP_CI_SERVICE_ACCOUNT` |
| AWS | `AWS_IMAGE`, `AWS_REGION`, `AWS_CI_ROLE_ARN` |
| Azure | `AZURE_IMAGE`, `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` |

An empty provider image variable disables publication for that experimental
provider. GCP is the initial production provider, so `GCP_IMAGE` and its three
OIDC identifiers are required before claiming a functioning production release
path.

Cloud trust must independently bind the token to the exact organization,
repository, numeric repository/owner identifiers where supported, the
`production` environment, and `refs/heads/main`. The workflow-side predicates
are defense in depth, not a replacement for cloud-side claim restrictions.

## Acceptance check

After the repository settings and GCP environment variables exist:

1. Open a pull request and confirm only `ci` runs and no environment approval or
   cloud authentication is requested.
2. Merge a reviewed change to `main`; confirm `ci` succeeds first.
3. Confirm `release` references the same triggering SHA and waits for the
   `production` environment approval.
4. Approve it as a different authorized reviewer and verify the registry tag is
   exactly that SHA.
5. Confirm the cloud audit log records workload federation and no service-account
   key or other long-lived credential was used.

P4.1 stops at validated image publication. Building only once, signing the
digest, retaining complete provenance, staging deployment, and production
promotion are P4.2 through P4.4.
