# Research Platform

One Docker image, five roles, elastic batch compute. Airflow orchestrates but
never computes; every task dispatches work to a batch runner that scales to
zero.

Runs on **Google Cloud, AWS or Azure**. One setting picks the provider:

```
RP_STORAGE_URI=gs://my-bucket                                  # GCP
RP_STORAGE_URI=s3://my-bucket                                  # AWS
RP_STORAGE_URI=abfs://research@acct.dfs.core.windows.net       # Azure
```

Nothing in `jobs/`, `dags/` or `compose/` branches on the provider. See
`PLAN.md` for the architecture and `terraform/README.md` for the one layer that
genuinely does not abstract.

## Layout

```
docker/           the one image + role dispatch
jobs/             task bodies -- no Airflow imports, runnable anywhere
  common/cloud.py the only file that knows provider names
dags/             orchestration only: when, and in what order
  _providers.py   one dispatch function per cloud, same signature
compose/          one file per node role (provider-neutral)
terraform/gcp/    \
terraform/aws/     > three parallel modules, same output names
terraform/azure/  /
ctl/              build / push / deploy / logs / shell / run
tests/            job logic + provider resolution + DAG integrity
```

## The three rules

**1. `jobs/` never imports Airflow.** Every job is `python -m jobs.<name>
--date YYYY-MM-DD`. That means a failing task is debugged by running it
directly, or in a notebook, instead of through the scheduler.

**2. Nothing outside `jobs/common/cloud.py` and `dags/_providers.py` branches
on the provider.** Storage is fsspec, which speaks `gs://`, `s3://` and
`abfs://` identically. Dispatch is one function per cloud behind a shared
signature, and a test asserts those signatures stay identical. Adding a fourth
provider is a change in two files plus a Terraform module.

**3. Data lands before the marker.** `write_parquet` then `mark_success`. A
reader that checks `is_complete()` can never see a half-written partition. The
`verify` task in every DAG enforces this from the other side.

## First run

```bash
cp .env.example .env          # fill in ONE provider block
uv lock                       # requires network; commit the result
make build CLOUD=gcp          # or aws, or azure
docker run --rm --env-file .env research-platform:dev job pull_ohlcv --date 2026-08-11
```

Local development needs no cloud at all -- set `RP_LOCAL_ROOT=/tmp/research-data`
and every storage call routes to disk through fsspec.

## Deploying

The image carries one provider's SDK stack, selected at build time. Installing
all three triples the image and guarantees a dependency conflict between the
boto, google and azure trees.

```bash
ctl build && ctl push         # provider inferred from RP_STORAGE_URI
ctl deploy control            # scheduler + api-server, and the batch job image
ctl deploy feed
ctl logs control --service scheduler
```

`ctl deploy` writes one SHA to one file per host and updates the batch job
definition in the same command, so all roles run the same tag by construction.
Deploys always pin a SHA; `:latest` exists only as a build cache source.

How "update the batch definition" lands differs by provider, and this is the one
place that difference leaks into operations:

| | GCP | AWS | Azure |
|---|---|---|---|
| Batch unit | Cloud Run Job | Batch job definition | Container Instance |
| Update | in place | new immutable revision | none -- tag ships in the env file |
| Cold start | seconds | seconds | tens of seconds to minutes |

## Access

Nothing listens on a public port.

```bash
ssh -N -L 8080:localhost:8080 you@control     # Airflow UI
ssh -N -L 8888:localhost:8888 you@notebook    # Jupyter
```

Instances have no external IP; reach them with
`gcloud compute ssh --tunnel-through-iap`.

## Credentials

There are none to manage on any of the three. Each provider's SDK finds an
attached identity through its own default credential chain:

| | Identity | Local dev |
|---|---|---|
| GCP | Service account attached to the instance | `gcloud auth application-default login` |
| AWS | IAM role via instance profile | `aws sso login` |
| Azure | User-assigned managed identity | `az login` |

Set `CLOUD_CREDS_PATH` and `CLOUD_CREDS_MOUNT` in `.env` to mount local
credentials read-only. No key file is ever downloaded, committed, or rotated.

## Adding a job

1. Write `jobs/my_job.py` with `def run(ctx) -> JobResult` and
   `entrypoint("my_job", run)` at the bottom.
2. Run it locally against `RP_LOCAL_ROOT` until it is right.
3. Add a DAG: one `dispatch(...)` and one `verify(...)`. The DAG integrity test
   fails if you forget the second.

## Known gaps

See `ADVERSARIAL_REVIEW.md` for the security and production-readiness findings
and `SECURITY.md` for repository handling rules.

* `jobs/pull_ohlcv.py` targets a placeholder REST shape. Replace `_fetch_bars`.
* `jobs/feed.py::parse_message` is vendor-specific.
* `jobs/build_pnl.py` assumes a `positions` dataset with `quantity`,
  `prev_mark`, and optionally `multiplier`. Nothing produces it yet.
* Terraform assumes existing networking on all three providers. The modules
  wire private database access but do not create a VPC/VNet: provide the GCP
  VPC/subnet self-links, AWS VPC/private subnets, or Azure VM, PostgreSQL, and
  ACI subnet IDs plus the linked PostgreSQL private DNS zone.
* The Azure path uses Container Instances, not Container Apps Jobs. Read
  `terraform/azure/README.md` before choosing Azure as your primary.
* `terraform/aws` assumes Fargate; there is no EC2 compute environment.
