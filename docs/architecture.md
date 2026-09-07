# Architecture

Jarvis separates orchestration, compute, and durable state. Compute nodes can be
replaced; object storage and the Airflow metadata database carry state.

## Components

| Component | Lifecycle | Responsibility |
|---|---|---|
| Control node | Always on | Airflow scheduler and API server; dispatches and polls |
| Managed PostgreSQL | Always on | Airflow metadata only |
| Batch runner | Per job | Executes compute-intensive job modules |
| Feed node | Always on | Runs a long-lived websocket consumer |
| Notebook node | On demand | Interactive research in the production image |
| Object storage | Durable | Parquet, artifacts, markers, and remote logs |

## Execution flow

1. An Airflow DAG determines when a job should run.
2. `dags/_providers.py` submits the image and command to the selected service.
3. The service invokes `job <module> --date <date>` in the shared image.
4. The job reads and writes through fsspec and creates a success marker only
   after its output is complete.
5. The DAG verifies the expected output before succeeding.

Airflow tasks exchange durable storage references, not research data via XCom.

## Provider boundary

| Concern | GCP | AWS | Azure |
|---|---|---|---|
| Object storage | GCS (`gs://`) | S3 (`s3://`) | ADLS Gen2 (`abfs://`) |
| Metadata database | Cloud SQL | RDS | PostgreSQL Flexible Server |
| Batch | Cloud Run Jobs | AWS Batch/Fargate | Container Instances |
| Registry | Artifact Registry | ECR | ACR |
| Identity | Service account | IAM role | Managed identity |
| Secret store | Secret Manager | Secrets Manager | Key Vault |

Storage abstracts through fsspec. Batch dispatch is provider-specific behind
matching function signatures. Terraform remains three modules because each
provider's IAM, networking, and compute models are materially different.

## Image roles

| Entrypoint command | Role |
|---|---|
| `scheduler` | Airflow scheduler |
| `api-server` | Airflow API server and UI |
| `jupyter` | JupyterLab |
| `feed` | Streaming feed process |
| `job <module> ...` | A single batch job |

Each provider receives a separate dependency build to avoid combining large,
potentially conflicting SDK trees.

## Storage contract

```text
<storage-root>/
├── raw/<source>/<dataset>/dt=YYYY-MM-DD/part-*.parquet
├── derived/<dataset>/dt=YYYY-MM-DD/part-*.parquet
├── artifacts/<job>/<run-id>/
└── airflow-logs/
```

Hive-style partitions allow query pruning. The harness makes completed
partitions idempotent unless `--force` is supplied.

## Invariants

- Jobs are plain Python and have no Airflow dependency.
- Cloud inference lives in `jobs/common/cloud.py`.
- DAG dispatch lives in `dags/_providers.py` with shared signatures.
- A partition's success marker is written after its data.
- Production services deploy an immutable Git SHA tag.

Architecture and DAG tests protect these boundaries.

## Trust boundaries

Jarvis assumes private cloud networking, attached workload identities, and
operator-controlled tunnels. It does not implement public ingress, multi-user
notebook isolation, or an application-level authorization layer.
