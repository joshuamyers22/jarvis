# No airflow.cfg here, deliberately

The plan called for a checked-in `airflow.cfg`. It was dropped in favour of
`AIRFLOW__<SECTION>__<KEY>` environment variables set in `compose/control.yml`.

Reasons:

1. A config file is a second source of truth that can differ between the
   scheduler and the API server. Env vars come from one compose file.
2. `airflow.cfg` keys move between sections across Airflow minor versions. A
   wrong env var fails loudly; a stale cfg key is silently ignored.
3. It keeps the image free of anything environment-specific, which is the point
   of the one-image design.

The plan's principle -- no literals in config -- is preserved. Only the
mechanism changed.
