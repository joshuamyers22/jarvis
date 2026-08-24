# Adversarial review

Reviewed 2026-08-23. The runtime boundaries are sensible, but this repository
is still a scaffold and must not be treated as production-ready.

## Fixed in this review

- Forced reruns now remove the prior completion marker before replacing data.
- Parquet and JSON objects publish through temporary objects instead of exposing
  partially written files.
- Storage path segments reject traversal and separators.
- Invalid or missing storage URIs fail closed; production cannot select local
  ephemeral storage.
- Job CLIs reject unknown arguments instead of silently ignoring typos.
- One-off runs propagate cloud and container failures to the caller.
- GCP batch jobs receive the required storage URI and provider environment.
- AWS defaults use an ARM notebook instance compatible with the selected AMI.
- AWS image deploys preserve the existing Terraform-managed job definition.
- Azure batch tasks now enforce the requested Airflow execution timeout.
- Git and Docker ignore common credential and Terraform secret files; CI has
  least-default permissions and cancellation of superseded runs.

## Open deployment blockers

1. Azure ACI dispatch still needs an end-to-end cloud integration test. Its
   maturity remains lower than the GCP and AWS paths.
2. VM bootstrap uses Debian's signed Docker packages. For stricter release
   reproducibility, replace bootstrapping with versioned machine images.
3. The example OHLCV and feed protocols are placeholders. Their schema,
   authentication, pagination, rate limiting, and malformed-message behavior
   need vendor-specific tests.

## Recommended private GitHub settings

Enable branch protection on `main`, require the CI check and one reviewed pull
request, block force pushes and branch deletion, enable secret scanning and push
protection, and restrict Actions to approved sources. Keep production
environment approvals and cloud OIDC roles separate from pull-request jobs.
