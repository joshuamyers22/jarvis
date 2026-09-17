# Deployment and operations

This describes the operational contract, not a substitute for a provider review.

## Provisioning

AWS and Azure currently expect existing private networking. For GCP, first
create the backend using the
[state bootstrap procedure](../terraform/bootstrap/gcp/README.md); do not create
an ad hoc bucket or reuse another environment's state prefix.
Deploy GCP through the [live environment roots](../terraform/live/gcp/README.md),
not by applying the reusable `terraform/gcp` module directly. Each live root
owns an isolated private VPC, Cloud NAT, private service access, private DNS,
and IAP-only SSH ingress alongside the platform resources.

Local bootstrap and runtime settings belong in their documented ignored env
files. Store only credential references or impersonation targets there; use
short-lived Application Default Credentials or workload identity rather than
embedding cloud keys.

The first live-root apply creates its deployer identity. Complete the documented
[GCP identity handoff](gcp-identity.md#initial-identity-handoff), grant that
deployer access to the remote-state bucket through the bootstrap stack, and use
impersonation for every later plan and apply. GitHub publishing uses the separate
CI identity and repository/environment/ref-bound OIDC federation.

Before a live apply, complete the
[GCP guardrail prerequisites](gcp-guardrails.md): approve the environment's
monthly budget, grant the deployer Billing Account Costs Manager on the selected
billing account, and arrange organization-policy evidence. After the apply,
verify the Monitoring email channel and deliver a test notification.
Keep cross-project data variables empty unless the source owner approved the
resource, workload, and role under the
[GCP data-access procedure](gcp-data-access.md). Review the resulting
`data_access_contract` output with every live plan.
Review the four-location [storage contract](storage-classes.md) before applying:
the existing data location must remain in place, logs and scratch receive only
their named workload identities, and backup storage has no runtime member.

```bash
scripts/gcp-live.sh dev validate
scripts/gcp-live.sh dev plan
scripts/gcp-live.sh dev apply
```

Do not commit backend credentials, variable files, plans, or state.

## Production configuration

- Keep `.env` mode `0600` and out of Git.
- Use workload identity and the provider secret store, not downloaded keys.
- Keep `RP_STORAGE_URI` and `AIRFLOW_REMOTE_LOGS` on the same provider.
- Set `RP_SCRATCH_URI` from Terraform's `scratch_uri` output and keep
  `AIRFLOW_REMOTE_LOGS` on the dedicated `airflow_logs_uri`.
- Pin `IMAGE_TAG` to a Git SHA.
- Retain loopback bindings for Airflow and Jupyter.

## Build and release

```bash
uv run ctl build
uv run ctl push
uv run ctl deploy all
```

The CLI rejects dirty trees so image contents correspond to the tag. CI builds
each provider image after checks pass. Registry publishing is skipped until the
corresponding repository variables and keyless identity secrets are configured.

## Access

```bash
gcloud compute ssh research-dev-control --project PROJECT_ID --zone us-central1-a \
  --tunnel-through-iap -- -N -L 8080:localhost:8080
gcloud compute ssh research-dev-notebook --project PROJECT_ID --zone us-central1-a \
  --tunnel-through-iap -- -N -L 8888:localhost:8888
```

GCP SSH is accepted only from IAP's TCP-forwarding range. Keep the tunnel flag;
do not add an external IP or broader firewall rule for administration. Only the
named `operator_principals` receive OS Login, port-22 IAP access, instance
start/stop, and actAs on the three VM service accounts.

## Routine checks

- Check scheduler/API health and remote Airflow log delivery.
- Run a synthetic batch job and verify its output and success marker.
- Monitor feed lag, reconnects, flush failures, and dropped records.
- Monitor database backups, restores, capacity, and connections.
- Monitor object growth, lifecycle rules, batch failures, quotas, and cost.
- Treat budget and quota notifications as incidents: acknowledge delivery,
  identify the affected environment, and record any approved budget or quota
  change in the infrastructure review.
- Confirm every role uses the intended immutable image tag.

Useful commands:

```bash
uv run ctl logs control --service scheduler
uv run ctl logs notebook --service jupyter
uv run ctl shell control
uv run ctl run pull_ohlcv --date 2026-08-11 --remote
```

## Deployment and recovery

Validate changes outside production, deploy one immutable tag, verify storage
and logs, then update remaining roles. Keep the previous tag for rollback.
Schema changes need explicit forward and rollback plans; the CLI does not
perform migrations.

Regularly test database restoration, host rebuilds, notebook-volume recovery,
versioned object recovery, and rollback to a known-good image SHA. Compute nodes
should be disposable; required research data belongs in durable storage.

See [ADVERSARIAL_REVIEW.md](../ADVERSARIAL_REVIEW.md) for current limitations.
