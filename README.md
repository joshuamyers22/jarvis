# Jarvis

Jarvis is a self-hosted research and batch-computing platform built around one
container image. The same Python environment runs Jupyter sessions, scheduled
Airflow workflows, streaming feeds, and elastic batch jobs on Google Cloud,
AWS, or Azure.

> [!IMPORTANT]
> Jarvis is an early-stage reference implementation, not a turnkey production
> service. Several data adapters are placeholders and the Terraform modules
> expect existing private networking. Review [Production readiness](#production-readiness)
> before deploying it with sensitive data or critical workloads.

## Why Jarvis

- **One image, five roles:** scheduler, API server, notebook, feed, and job.
- **Portable jobs:** `jobs/` modules run from a terminal, notebook, scheduler,
  or batch service without importing Airflow.
- **Elastic compute:** Airflow dispatches work; it does not perform the work.
- **Provider-neutral storage:** fsspec provides one path for GCS, S3, and ADLS.
- **Reproducible releases:** dependencies are locked and production images use
  immutable Git SHA tags.
- **Keyless cloud access:** deployed roles use attached workload identities.

## Architecture

```text
 Notebook ───────┐                         ┌─ GCP Cloud Run Jobs
 Feed ───────────┼── Object storage       ├─ AWS Batch
 Batch jobs ─────┘                         └─ Azure Container Instances
                         ▲
                         │
                 Airflow control node ─── Managed PostgreSQL
                  (dispatch and polling)     (metadata only)
```

`RP_STORAGE_URI` selects the provider:

```dotenv
RP_STORAGE_URI=gs://my-bucket
RP_STORAGE_URI=s3://my-bucket
RP_STORAGE_URI=abfs://research@account.dfs.core.windows.net
```

See [Architecture](docs/architecture.md) for component boundaries, execution
flow, storage conventions, and the provider comparison.

## Quick start

Prerequisites: Python 3.12, [uv](https://docs.astral.sh/uv/), Docker with
Compose v2, and Git.

```bash
git clone https://github.com/joshuamyers22/jarvis.git
cd jarvis
uv sync --frozen --extra dev --extra gcp
uv run ruff check .
uv run mypy jobs ctl
uv run pytest -q
```

To run without cloud infrastructure, copy `.env.example` to `.env`, set
`RP_LOCAL_ROOT=.local-data`, and build an image:

```bash
docker build -f docker/Dockerfile --build-arg CLOUD=gcp \
  -t research-platform:dev .
docker run --rm --env-file .env research-platform:dev \
  job pull_ohlcv --date 2026-08-11
```

The bundled OHLCV adapter targets a placeholder API shape. Replace
`jobs/pull_ohlcv.py::_fetch_bars` before expecting real market data. See
[Getting started](docs/getting-started.md) for the complete walkthrough.

## Repository map

```text
jobs/             provider-neutral jobs and shared runtime code
dags/             Airflow scheduling, dispatch, and output verification
compose/          control, feed, and notebook service definitions
docker/           shared image and role-dispatch entrypoint
terraform/        parallel GCP, AWS, and Azure modules
ctl/              build, push, deploy, logs, shell, and run commands
tests/            architecture, job, provider, and DAG checks
docs/             setup, design, notebook, and operations guides
```

## Documentation

- [Getting started](docs/getting-started.md)
- [Architecture](docs/architecture.md)
- [Notebook storage and cross-machine workflows](docs/notebooks.md)
- [Deployment and operations](docs/operations.md)
- [Terraform provider guide](terraform/README.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

## Design invariants

1. `jobs/` never imports Airflow.
2. Provider branching is confined to `jobs/common/cloud.py` and
   `dags/_providers.py`.
3. Jobs write data before their success marker.
4. Research data and artifacts live in object storage; compute is disposable.
5. Deployed services use the same immutable image tag.

Tests enforce the first three invariants.

## Production readiness

Before production use, address [the readiness findings](ADVERSARIAL_REVIEW.md):

- implement and validate the market-data and feed adapters;
- provide private networking and remote Terraform state;
- configure least-privilege identities and provider secret stores;
- add backups, restore tests, monitoring, alerts, and runbooks;
- choose and test a notebook backup/synchronization strategy;
- validate resource sizing, retention, recovery objectives, and cost controls.

Azure currently uses Container Instances rather than Container Apps Jobs; read
[the Azure notes](terraform/azure/README.md) before selecting it.

## License

No license is currently granted. The repository is publicly viewable, but that
does not by itself grant permission to copy, modify, or redistribute the code.
Add an explicit license before encouraging reuse or accepting contributions.
