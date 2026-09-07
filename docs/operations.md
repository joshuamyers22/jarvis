# Deployment and operations

This describes the operational contract, not a substitute for a provider review.

## Provisioning

Choose one module under `terraform/`. The modules expect existing private
networking and should use encrypted, versioned remote state with locking.

```bash
terraform -chdir=terraform/gcp init -backend-config=backend.hcl
terraform -chdir=terraform/gcp plan -var-file=prod.tfvars -out=plan.tfplan
terraform -chdir=terraform/gcp apply plan.tfplan
```

Do not commit backend credentials, variable files, plans, or state.

## Production configuration

- Keep `.env` mode `0600` and out of Git.
- Use workload identity and the provider secret store, not downloaded keys.
- Keep `RP_STORAGE_URI` and `AIRFLOW_REMOTE_LOGS` on the same provider.
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
ssh -N -L 8080:localhost:8080 user@control-host
ssh -N -L 8888:localhost:8888 user@notebook-host
```

Use IAP, Session Manager, or Bastion rather than adding public IPs solely for
administration.

## Routine checks

- Check scheduler/API health and remote Airflow log delivery.
- Run a synthetic batch job and verify its output and success marker.
- Monitor feed lag, reconnects, flush failures, and dropped records.
- Monitor database backups, restores, capacity, and connections.
- Monitor object growth, lifecycle rules, batch failures, quotas, and cost.
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
