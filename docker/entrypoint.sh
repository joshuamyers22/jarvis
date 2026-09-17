#!/usr/bin/env bash
# =============================================================================
# Role dispatch. The image is identical everywhere; argv[1] selects behaviour.
#
#   docker run IMAGE scheduler
#   docker run IMAGE api-server
#   docker run IMAGE migration
#   docker run IMAGE jupyter
#   docker run IMAGE feed
#   docker run IMAGE job pull_ohlcv --date 2026-08-11
# =============================================================================
set -euo pipefail

wait_for_db() {
  echo "[entrypoint] waiting for metadata database"
  for _ in $(seq 1 60); do
    # Airflow resolves the SQLAlchemy URL from its secrets backend, so the
    # database password never needs to enter this script or the host env file.
    if airflow db check >/dev/null 2>&1
    then
      echo "[entrypoint] database is up"
      return 0
    fi
    sleep 2
  done
  echo "[entrypoint] database never became reachable" >&2
  exit 1
}

wait_for_migrations() {
  echo "[entrypoint] waiting for explicit metadata migration"
  airflow db check-migrations --migration-wait-timeout 60
}

case "${1:-}" in
  scheduler)
    wait_for_db
    wait_for_migrations
    exec airflow scheduler
    ;;

  api-server)
    wait_for_db
    wait_for_migrations
    exec airflow api-server --host 0.0.0.0 --port 8080
    ;;

  migration-preflight)
    wait_for_db
    exec python -m ctl.database_migration preflight
    ;;

  migration-current)
    wait_for_db
    exec python -m ctl.database_migration current
    ;;

  migration)
    wait_for_db
    python -m ctl.database_migration preflight
    echo "[entrypoint] applying the candidate image's migration graph"
    timeout --foreground --kill-after=30s 1800s \
      airflow db migrate --use-migration-files
    airflow db check-migrations --migration-wait-timeout 60
    exec python -m ctl.database_migration current
    ;;

  release-probe)
    shift
    exec python -m ctl.release_probe "$@"
    ;;

  jupyter)
    exec jupyter lab --config=/etc/jupyter/jupyter_server_config.py
    ;;

  feed)
    exec python -m jobs.common.runtime_secrets exec --role feed -- python -m jobs.feed
    ;;

  job)
    shift
    [ $# -ge 1 ] || { echo "[entrypoint] usage: job <module> [args...]" >&2; exit 2; }
    module="$1"; shift
    exec python -m jobs.common.runtime_secrets exec --role job -- \
      python -m "jobs.${module}" "$@"
    ;;

  *)
    exec "$@"
    ;;
esac
