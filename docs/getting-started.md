# Getting started

This guide runs Jarvis locally without provisioning cloud infrastructure.

## 1. Install and verify

Install Python 3.12, uv, Git, and Docker with Compose v2, then run:

```bash
git clone https://github.com/joshuamyers22/jarvis.git
cd jarvis
uv sync --frozen --extra dev --extra gcp
uv run ruff check .
uv run mypy jobs ctl
uv run pytest -q
```

The provider extra imports the GCP Airflow operator during DAG tests. It does
not authenticate to or create resources in GCP.

## 2. Configure local storage

```bash
cp .env.example .env
chmod 600 .env
```

Set these development values in `.env`:

```dotenv
RP_ENV=dev
RP_LOCAL_ROOT=.local-data
RP_STORAGE_URI=gs://unused-in-local-mode
IMAGE=research-platform
IMAGE_TAG=dev
```

`RP_LOCAL_ROOT` routes runtime storage calls to the local filesystem.
`RP_STORAGE_URI` remains present because configuration and image-provider
selection expect a provider-shaped URI.

## 3. Build and run

```bash
docker build -f docker/Dockerfile --build-arg CLOUD=gcp \
  -t research-platform:dev .
docker run --rm --env-file .env research-platform:dev \
  job pull_ohlcv --date 2026-08-11
```

Every job follows `job <module> --date YYYY-MM-DD`. The included market-data
endpoint is a placeholder and must be replaced for a real-data pull.

Jarvis builds a separate image per provider SDK stack. Use `aws` or `azure`
when testing those environments.

## 4. Use the CLI

```bash
uv run ctl --help
uv run ctl build --allow-dirty
uv run ctl run pull_ohlcv --date 2026-08-11
```

Build and deploy operations reject a dirty tree by default because the Git SHA
would not uniquely describe the image.

## Next steps

- Read [Notebook workflows](notebooks.md) before storing research work.
- Read [Architecture](architecture.md) before adding a job or provider.
- Read [Operations](operations.md) and the [Terraform guide](../terraform/README.md)
  before deploying.
