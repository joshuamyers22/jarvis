#!/usr/bin/env bash
# =============================================================================
# Role dispatch. The image is identical everywhere; argv[1] selects behaviour.
#
#   docker run IMAGE scheduler
#   docker run IMAGE api-server
#   docker run IMAGE jupyter
#   docker run IMAGE feed
#   docker run IMAGE job pull_ohlcv --date 2026-08-11
# =============================================================================
set -euo pipefail

wait_for_db() {
  echo "[entrypoint] waiting for metadata database at ${AIRFLOW_DB_HOST}:${AIRFLOW_DB_PORT:-5432}"
  for _ in $(seq 1 60); do
    if python - <<'PY' 2>/dev/null
import os, sys
import psycopg2
try:
    psycopg2.connect(
        host=os.environ["AIRFLOW_DB_HOST"],
        port=int(os.environ.get("AIRFLOW_DB_PORT", 5432)),
        user=os.environ["AIRFLOW_DB_USER"],
        password=os.environ["AIRFLOW_DB_PASSWORD"],
        dbname=os.environ["AIRFLOW_DB_NAME"],
        connect_timeout=3,
    ).close()
except Exception:
    sys.exit(1)
PY
    then
      echo "[entrypoint] database is up"
      return 0
    fi
    sleep 2
  done
  echo "[entrypoint] database never became reachable" >&2
  exit 1
}

case "${1:-}" in
  scheduler)
    wait_for_db
    airflow db migrate          # idempotent; safe on every start
    exec airflow scheduler
    ;;

  api-server)
    wait_for_db
    exec airflow api-server --host 0.0.0.0 --port 8080
    ;;

  jupyter)
    exec jupyter lab --config=/etc/jupyter/jupyter_server_config.py
    ;;

  feed)
    exec python -m jobs.feed
    ;;

  job)
    shift
    [ $# -ge 1 ] || { echo "[entrypoint] usage: job <module> [args...]" >&2; exit 2; }
    module="$1"; shift
    exec python -m "jobs.${module}" "$@"
    ;;

  *)
    exec "$@"
    ;;
esac
