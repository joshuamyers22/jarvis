# Research Platform — Project Plan

A self-hosted research and production environment: one Docker image, elastic batch
compute, Airflow for scheduling, notebooks for interactive work, object storage as
the single source of truth.

**Portable across Google Cloud, AWS and Azure.** One setting -- `RP_STORAGE_URI` --
selects the provider; the runtime contains no provider branch outside two files.

---

## 1. Goals

| # | Goal | Why it matters |
|---|------|----------------|
| G1 | One image, many roles | A notebook that works in research works identically in production — same interpreter, same pinned deps |
| G2 | Disposable compute | Any instance can be destroyed and rebuilt without data loss or manual reconfiguration |
| G3 | Elastic batch | A 4 GB API pull and a 256 GB backtest use the same image at different sizes, with no idle capacity billed |
| G4 | No downloaded credentials | Attached identities only; nothing to rotate, nothing to leak |
| G5 | Reproducible runs | Every job takes an explicit date/window and is safe to rerun |
| G6 | Provider portability | Moving clouds changes config and one Terraform module, not job or DAG code |

### Non-goals (explicitly deferred)

- Running on more than one provider *simultaneously* — portable is not the same
  as federated, and cross-cloud egress makes the latter expensive
- Multi-user auth / JupyterHub — solo use, SSH tunnels are sufficient
- Kubernetes — revisit only if a specific workload demands it
- A general-purpose provisioning framework — Terraform owns infrastructure, the CLI owns deploys
- Real-time / low-latency execution — this platform is for research and batch

---

## 2. Architecture

### Components

| Component | Sizing | Lifecycle | Responsibility |
|-----------|--------|-----------|----------------|
| Control node | Smallest instance | Always on | Airflow scheduler + API server. Orchestrates only — never computes |
| Metadata DB | Smallest managed Postgres | Always on | Airflow metadata **only**. No research data |
| Batch runner | Per-job sizing | Scales to zero | Where all real work executes (see provider mapping below) |
| Feed node | Small | Always on | Long-running websocket consumer, isolated from Airflow |
| Notebook node | Sized for comfort | Start/stop on demand | Interactive research |
| Object storage | — | Durable | Parquet, artifacts, Airflow remote logs |

### Provider mapping

| Concern | GCP | AWS | Azure |
|---|---|---|---|
| Object storage | GCS (`gs://`) | S3 (`s3://`) | ADLS Gen2 (`abfs://`) |
| Metadata DB | Cloud SQL | RDS | Postgres Flexible Server |
| Batch runner | Cloud Run Jobs | Batch on Fargate | Container Instances |
| Registry | Artifact Registry | ECR | ACR |
| Secrets | Secret Manager | Secrets Manager | Key Vault |
| Workload identity | Attached service account | IAM role + instance profile | User-assigned managed identity |
| Shell without public IP | IAP tunnel | SSM Session Manager | Bastion |
| Airflow log sink | `gs://` | `s3://` | `wasb://` |

### What abstracts, and what does not

**Abstracts cleanly.** Storage (fsspec handles all three schemes identically),
config, secrets backend, remote logging, and the compose files — all
provider-neutral with no branching.

**Abstracts adequately.** Batch dispatch: one function per cloud in
`dags/_providers.py`, sharing a signature that a test enforces. No DAG contains
a provider branch.

**Does not abstract.** Terraform. IAM, networking and identity are different
models, not the same model with different names — a GCP per-resource IAM
binding, an AWS policy document attached to an assumable role, and an Azure role
assignment at a scope do not reduce to a common shape. Three parallel modules
emitting identical output names is the honest answer; a single parameterized
module would be unreadable and would plan badly.

**Leaks into operations.** The batch unit differs in kind: a Cloud Run Job is
mutable, an AWS Batch job definition is immutable (new revisions), and an Azure
Container Instance has no persistent definition at all. `ctl deploy` handles all
three, but the Azure path carries the image tag in the control node's env file
rather than in a definition.

### Execution model

```
                      ┌──────────────────┐
                      │  Managed Postgres│
                      │  (Airflow meta)  │
                      └────────▲─────────┘
                               │
   ┌───────────────┐    ┌──────┴──────┐    ┌──────────────────┐
   │ Notebook node │    │Control node │───▶│  Batch runner    │
   │  (on demand)  │    │ scheduler + │    │ (scales to zero) │
   └───────┬───────┘    │ api-server  │    └────────┬─────────┘
           │            └─────────────┘             │
           │                                        │
           │            ┌─────────────┐             │
           │            │  Feed node  │             │
           │            │ (always on) │             │
           │            └──────┬──────┘             │
           │                   │                    │
           └───────────────────┴────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │   Object storage    │
                    │  parquet · logs ·   │
                    │      artifacts      │
                    └─────────────────────┘
```

Airflow tasks **dispatch and poll**; they do not compute. Data moves between tasks
through storage paths, never XCom.

### Key decisions and their rationale

| Decision | Chosen | Rejected | Rationale |
|----------|--------|----------|-----------|
| Executor | LocalExecutor on control node | Celery, KubernetesExecutor | Control node only dispatches; distribution happens at the batch layer |
| Provider selection | Derived from `RP_STORAGE_URI` | Separate `RP_CLOUD` flag | One setting cannot disagree with itself; an explicit flag can |
| Provider SDKs | One stack per image, via build arg | All three in one image | Three SDK trees triple the image and conflict on shared deps |
| Compute | Serverless batch jobs | Fixed worker fleet | No idle spend, no capacity planning, per-job sizing |
| DAG distribution | Baked into image | git-sync, bucket sync | Immutable — makes scheduler/worker DAG disagreement structurally impossible |
| Shared state | Object storage | NFS / EFS / Filestore | Shared mutable filesystems become the bottleneck and the outage |
| Credentials | Attached service accounts | Downloaded JSON keys | Same code path locally and in cloud; nothing to rotate |
| Secrets | Secret Manager backend | Per-instance `.env` | N env files drift; one backend does not |
| Dependency mgmt | `uv` + committed lockfile | bare pip | Airflow's dep tree is brittle; a lockfile makes rebuilds deterministic |

### Identity model

Four identities, each minimally scoped — service accounts on GCP, IAM roles on
AWS, user-assigned managed identities on Azure:

- `sa-control` — submit batch jobs, read/write Airflow logs bucket, connect to Postgres
- `sa-job` — read/write data bucket, read secrets it needs
- `sa-feed` — write to data bucket, read feed credentials
- `sa-notebook` — read data bucket, write scratch prefix

No single account holds all permissions.

---

## 3. Repository structure

```
infra/
├── README.md
├── pyproject.toml                 # packages ctl/ and jobs/; console_scripts entry point
├── uv.lock                        # committed — the reproducibility guarantee
├── .env.example                   # committed template; .env is gitignored
├── .gitignore
│
├── docker/
│   ├── Dockerfile                 # the one base image
│   ├── entrypoint.sh              # role dispatch
│   ├── airflow/
│   │   └── airflow.cfg            # env-var interpolated, no literals
│   └── jupyter/
│       └── jupyter_server_config.py
│
├── jobs/                          # task bodies — NO airflow imports
│   ├── __init__.py
│   ├── common/
│   │   ├── cloud.py               # the only file that names providers
│   │   ├── storage.py             # fsspec: one code path for all three
│   │   ├── config.py              # env parsing, one place
│   │   ├── harness.py             # date, idempotency, size check, marker
│   │   └── logging.py
│   ├── feed.py                    # long-running websocket consumer
│   ├── pull_ohlcv.py
│   ├── build_pnl.py
│   └── run_var.py
│
├── dags/                          # orchestration only — when and in what order
│   ├── _common.py                 # dispatch + verify, provider-neutral
│   ├── _providers.py              # one dispatch fn per cloud
│   ├── daily_pnl.py
│   ├── hourly_ohlcv.py
│   └── nightly_risk.py
│
├── compose/
│   ├── control.yml                # scheduler + api-server
│   ├── feed.yml                   # restart: always
│   └── notebook.yml
│
├── terraform/                     # three parallel modules, same outputs
│   ├── README.md                  # why they are not one module
│   ├── gcp/
│   ├── aws/
│   └── azure/                     # read azure/README.md before choosing it
│
├── ctl/                           # deploy CLI — five commands, resist growth
│   ├── __init__.py
│   ├── main.py                    # Typer app
│   └── commands/
│       ├── build.py
│       ├── deploy.py
│       ├── logs.py
│       └── shell.py
│
├── tests/
│   ├── test_jobs/                 # jobs are plain functions — easy to test
│   └── test_dags/                 # DAG import + structure validation
│
└── .github/workflows/
    ├── build.yml                  # build, tag with SHA, push
    └── test.yml
```

### The `jobs/` ÷ `dags/` split

The most important structural rule in the repo.

A module in `jobs/` is plain Python with a `main()` that reads config from the
environment and writes to object storage. It imports no Airflow. It can be run from
a terminal, from a notebook, or inside a batch container — which means a failing
task is debugged by running it directly, not by fighting the scheduler.

A module in `dags/` declares schedule, ordering, and retries. Nothing else.

### Entrypoint contract

```bash
#!/usr/bin/env bash
set -euo pipefail
case "$1" in
  scheduler)   exec airflow scheduler ;;
  api-server)  exec airflow api-server ;;
  jupyter)     exec jupyter lab --ip=127.0.0.1 --no-browser ;;
  feed)        exec python -m jobs.feed ;;
  job)         shift; exec python -m "jobs.$1" "${@:2}" ;;
  *)           exec "$@" ;;
esac
```

One image, five roles. The batch runner invokes it as
`job run_var --date 2026-08-11`.

### Dockerfile layer order

Cache-optimal, cheapest-changing first:

1. `python:3.12-slim` base
2. System libs — `build-essential`, `libpq-dev`, `git`
3. `uv`
4. `pyproject.toml` + `uv.lock` → `uv sync --frozen`
5. Config files — `airflow.cfg`, jupyter config
6. `jobs/`, `dags/`, `ctl/` — changes most often, lands last

### Storage path convention

Decide this once, before writing any job:

```
gs://<bucket>/
├── raw/<source>/<dataset>/dt=YYYY-MM-DD/part-*.parquet
├── derived/<dataset>/dt=YYYY-MM-DD/part-*.parquet
├── artifacts/<job>/<run_id>/
└── airflow-logs/
```

Hive-style partitioning means DuckDB can read the whole history with a glob and
push partition filters down.

---

## 4. Build sequence

Ordered so that real work is possible early and each milestone is independently
useful.

### M1 — Image
Dockerfile, `pyproject.toml`, lockfile, entrypoint. **Done when:** all five roles
start locally under `docker run` and `uv sync --frozen` reproduces byte-identically
on a clean machine.

### M2 — Notebook + storage
Terraform for bucket, notebook instance, `sa-notebook`. Jupyter bound to
`127.0.0.1`, reached over `ssh -N -L 8888:localhost:8888`. **Done when:** a notebook
reads and writes parquet in the bucket with zero credential files on disk.

> Stop here and use it for real work for a week. Everything downstream is shaped by
> what actually annoys you at this stage.

### M3 — Orchestration
Managed Postgres, control node, `compose/control.yml`, one batch job definition, one
DAG with a single dispatch task. **Done when:** a scheduled DAG dispatches a batch
job, the job writes to storage, and the task fails loudly if the object is missing.

### M4 — Port the jobs
Move existing scheduled work into `jobs/` one module at a time, each with an explicit
date argument and idempotent output path. **Done when:** reruns are safe and produce
identical output.

### M5 — Feed node
Websocket consumer as its own always-on service, deliberately isolated from the
control node. **Done when:** an Airflow restart cannot interrupt the feed, and a feed
OOM cannot interrupt the scheduler.

### M6 — CI
Build on push, tag with git SHA plus moving `latest`, push to registry, layer caching.
Deploys pin to a SHA. **Done when:** rollback is a one-variable change.

### M7 — CLI
`build`, `deploy`, `logs`, `shell`, `run`. Written last, once the commands you
actually retype are known.

---

## 5. Operational invariants

Design against these from the start; each has a cheap prevention and an expensive cure.

**Silent partial failure.** With remote dispatch, a task can report success because
the job was *submitted*. Always check the job's exit code, and assert the expected
output object exists with a plausible size before downstream tasks run.

**Image drift across roles.** All roles must run the same tag. Write one SHA to one
place that every compose file and job definition reads. Mismatched tags produce
failures that masquerade as data bugs.

**XCom misuse.** XCom passes through the metadata DB. Small scalars only — a path
string, a row count. Never a dataframe.

**Not everything is a DAG.** Airflow schedules work with a discrete start and end. A
process meant to hold a connection open indefinitely is a service. Forcing it into
Airflow yields tasks that look successful while the connection is dead.

**Idempotency.** Every job takes an explicit date/window and overwrites its output
path deterministically. Reruns will be constant.

---

## 6. Open questions

- [ ] Which provider is primary. All three are scaffolded, but Azure's batch
      path is materially weaker (Container Instances, slow cold start) — see
      `terraform/azure/README.md`
- [ ] Retention policy for `raw/` — lifecycle rules to cold storage after N days?
- [ ] Alerting destination on DAG failure — email, or something with an actual pager?
- [ ] Whether `dags/` + `jobs/` eventually split into their own repo, separate from
      infrastructure. Defer until the infra stops changing
- [ ] Backup posture for the metadata DB — automated snapshots are likely sufficient
      given all real data lives in object storage

---

## 7. Escape hatches

Signals that a decision above should be revisited, and what to do:

| Signal | Change |
|--------|--------|
| Azure becomes primary and ACI cold starts hurt | Container Apps Jobs via a `BashOperator` wrapper, or AKS + `KubernetesPodOperator` |
| Batch cold-start latency dominates run time | Move to a warm fixed worker pool (Celery + managed Redis) |
| A workload needs GPUs or exotic hardware | Kubernetes with per-task resource requests (managed/Autopilot) |
| More than one person needs notebooks | JupyterHub, or per-user notebook instances behind IAP |
| Control node saturates on scheduling | Split scheduler and API server; scale Postgres before anything else |
