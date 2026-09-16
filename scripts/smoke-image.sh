#!/usr/bin/env bash
# Smoke all five runtime roles from one provider-specific Jarvis image.

set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <image> <gcp|aws|azure>" >&2
  exit 2
fi

image=$1
cloud=$2
case "$cloud" in
  gcp)
    storage_uri=gs://jarvis-smoke
    ;;
  aws)
    storage_uri=s3://jarvis-smoke
    ;;
  azure)
    storage_uri=abfs://research@jarvissmoke.dfs.core.windows.net
    ;;
  *)
    echo "unsupported cloud: $cloud" >&2
    exit 2
    ;;
esac

run_suffix="${cloud}-$$"
network="jarvis-smoke-${run_suffix}"
database="jarvis-smoke-db-${run_suffix}"
scheduler="jarvis-smoke-scheduler-${run_suffix}"
api="jarvis-smoke-api-${run_suffix}"
notebook="jarvis-smoke-notebook-${run_suffix}"
feed="jarvis-smoke-feed-${run_suffix}"

docker image inspect "$image" >/dev/null
fernet_key=$(docker run --rm --entrypoint python "$image" -c \
  'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')

cleanup() {
  docker rm -f "$feed" "$notebook" "$api" "$scheduler" "$database" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT

wait_for() {
  local label=$1
  shift
  for _ in $(seq 1 90); do
    if "$@" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "timed out waiting for $label" >&2
  return 1
}

common_env=(
  --env RP_ENV=dev
  --env RP_CLOUD="$cloud"
  --env RP_STORAGE_URI="$storage_uri"
  --env RP_PROJECT_ID=jarvis-smoke
  --env RP_REGION=us-central1
  --env RP_RESOURCE_GROUP=jarvis-smoke
  --env RP_BATCH_JOB_NAME=research-job
  --env RP_BATCH_JOB_QUEUE=research-queue
  --env RP_IMAGE=jarvis-smoke
  --env RP_IMAGE_TAG=smoke
  --env RP_AZURE_ACI_SUBNET_ID=/subscriptions/smoke/subnets/jobs
  --env RP_AZURE_JOB_IDENTITY_ID=/subscriptions/smoke/identities/jobs
  --env AIRFLOW_DB_HOST="$database"
  --env AIRFLOW_DB_PORT=5432
  --env AIRFLOW_DB_USER=airflow
  --env AIRFLOW_DB_PASSWORD=airflow-smoke
  --env AIRFLOW_DB_NAME=airflow
  --env AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://airflow:airflow-smoke@${database}:5432/airflow
  --env AIRFLOW__CORE__FERNET_KEY="$fernet_key"
  --env AIRFLOW__CORE__EXECUTOR=LocalExecutor
  --env AIRFLOW__CORE__LOAD_EXAMPLES=False
  --env AIRFLOW__LOGGING__REMOTE_LOGGING=False
)

docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$image" \
  | grep -qx "RP_IMAGE_CLOUD=${cloud}"

docker network create "$network" >/dev/null
docker run -d --name "$database" --network "$network" \
  --env POSTGRES_USER=airflow \
  --env POSTGRES_PASSWORD=airflow-smoke \
  --env POSTGRES_DB=airflow \
  postgres:16@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94 >/dev/null
wait_for PostgreSQL docker exec "$database" pg_isready -U airflow -d airflow

docker run -d --name "$scheduler" --network "$network" \
  "${common_env[@]}" "$image" scheduler >/dev/null
if ! wait_for scheduler docker exec "$scheduler" sh -c \
  'airflow jobs check --job-type SchedulerJob --hostname "$(hostname)"'; then
  docker logs "$scheduler" >&2
  exit 1
fi

docker run -d --name "$api" --network "$network" \
  "${common_env[@]}" "$image" api-server >/dev/null
if ! wait_for "Airflow API" docker exec "$api" \
  curl -fsS http://127.0.0.1:8080/api/v2/monitor/health; then
  docker logs "$api" >&2
  exit 1
fi

docker run -d --name "$notebook" --network "$network" "$image" jupyter >/dev/null
if ! wait_for Jupyter docker exec "$notebook" \
  curl -fsS http://127.0.0.1:8888/api/status; then
  docker logs "$notebook" >&2
  exit 1
fi

docker run -d --name "$feed" --network "$network" \
  --env RP_ENV=dev \
  --env RP_LOCAL_ROOT=/tmp/research-data \
  --env RP_FEED_WS_URL=ws://127.0.0.1:9 \
  "$image" feed >/dev/null
sleep 3
[[ "$(docker inspect --format '{{.State.Running}}' "$feed")" == "true" ]]

docker run --rm "$image" job pull_ohlcv --help >/dev/null

echo "all Jarvis roles passed for ${cloud}"
