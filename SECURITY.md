# Security policy

This is a private, single-operator repository. Report suspected vulnerabilities
directly to the repository owner; do not open an issue containing credentials,
customer data, infrastructure identifiers, or exploit details.

## Secrets

- Never commit `.env`, Terraform variable files, private keys, cloud credential
  exports, database dumps, or notebook outputs containing sensitive data.
- Use workload identity in deployed environments and each cloud's secret store
  for application secrets.
- Treat Terraform state as sensitive. Store it in an encrypted remote backend
  with versioning, access logging, and least-privilege access.
- If a secret reaches Git history, revoke it first. Removing the file from a
  later commit does not remove the exposure.

## Dependency and image updates

Dependency updates must pass lint, type checks, tests, and all three provider
image builds. Production deploys use immutable Git SHA image tags; `latest` is
only a cache hint.
