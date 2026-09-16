# Security policy

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability, credential exposure,
customer data, infrastructure identifiers, or exploit details.

Use GitHub's private vulnerability reporting feature on the repository's
**Security** tab. If it is unavailable, contact the repository owner through
their GitHub profile and request a private communication channel. Include the
affected revision, impact, reproduction steps, and suggested mitigation when
possible.

There is currently no guaranteed response-time SLA. Please allow the maintainer
time to acknowledge and investigate a report before public disclosure.

## Supported versions

Jarvis is pre-1.0 and supports only the latest revision of `main`. Older commits
and downstream forks do not receive security updates.

## Repository and secret handling

- Never commit `.env`, Terraform variables or state, private keys, cloud
  credentials, database dumps, or sensitive notebook outputs.
- Use attached workload identity and the provider's secret store in production.
- Keep Terraform state encrypted, versioned, locked, access-logged, and private.
- Clear sensitive notebook outputs and metadata before publication.
- If a secret reaches Git history, revoke or rotate it first. A later deletion
  does not remove the exposure.

## Dependency and image updates

Updates must pass lint, type checks, tests, Terraform validation, and all three
provider image builds. Production deploys use immutable Git SHA image tags;
`latest` is only a build-cache hint.

Pull requests scan locked dependencies, repository secrets, infrastructure
configuration, and every provider image. Fixed high or critical findings block
merging. Each image build also emits an SPDX JSON SBOM retained with CI evidence.

A vulnerability exception requires a private security issue containing the
affected component and version, exploitability assessment, compensating control,
named owner, review date, and expiry no later than 30 days. The exception must be
approved by a code owner and referenced from the workflow or scanner ignore file.
Expired exceptions fail the build. Detected credentials and private keys are never
eligible for an exception; rotate or revoke them and remove them from history.

## Deployment boundary

Jarvis does not provide multi-user authorization, public ingress, or a hardened
network perimeter. Airflow and Jupyter bind to loopback and are intended to be
reached through an authenticated tunnel. Operators own cloud IAM, network
policy, database security, backups, monitoring, and incident response.
