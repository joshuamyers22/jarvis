# Runtime secrets

Production deployment files contain secret identifiers only. Secret values are
resolved after a workload starts, using its attached service account. No service
account key or application credential file is copied to a host.

## GCP contract

Terraform creates four Secret Manager containers and grants access at the
individual-secret boundary:

| Secret | Consumer | Retrieval path |
|---|---|---|
| `airflow-config-sql-alchemy-conn` | control | Airflow config secrets backend |
| `airflow-config-fernet-key` | control | Airflow config secrets backend |
| `research-ENV-vendor-credentials` | batch job | runtime credential loader |
| `research-ENV-feed-credentials` | feed VM | runtime credential loader |

The database URL, database password, and Fernet key are generated ephemerally
during apply and written through provider write-only fields. Terraform state
contains neither value. Vendor and feed secret containers intentionally have no
version after apply; an operator seeds them without passing their values through
Terraform.

The vendor and feed values use one narrow JSON format:

```json
{"headers":{"Authorization":"Bearer REDACTED"}}
```

At process start, the loader fetches that JSON and places it only in the child
process environment. HTTP and websocket clients parse the `headers` object. The
loader never prints the reference or value and fails closed in production if its
required reference is absent.

## Seed or rotate workload credentials

First obtain the environment-specific identifiers:

```bash
scripts/gcp-live.sh prod output
```

Use the `runtime_secret_contract` section of that output.

Read the complete JSON value without echoing it or placing it in shell history,
then add a new immutable version:

```bash
read -r -s -p 'Secret JSON: ' JARVIS_SECRET_VALUE
printf '\n'
printf '%s' "$JARVIS_SECRET_VALUE" | \
  gcloud secrets versions add SECRET_ID --project PROJECT_ID --data-file=-
unset JARVIS_SECRET_VALUE
```

Use the same operation for rotation. Confirm the owning workload can start and
authenticate, then disable the previous version. Do not destroy the previous
version until the rollback window closes.

To rotate the generated database and Fernet credentials, increment the matching
`password_wo_version` / `secret_data_wo_version` generation in
`terraform/gcp/database.tf`, apply in development and staging, and promote the
reviewed change to production. Database password and SQLAlchemy URL generations
must move together. Rotating the Fernet key also requires Airflow's documented
multi-key re-encryption procedure; replacing it without re-encrypting existing
metadata makes stored connection values unreadable.

## Deployment boundary

`ctl deploy` reads the operator's ignored `.env`, rejects known secret-bearing
keys, and generates a mode-`0600` temporary file from an explicit allowlist. It
copies that file as `runtime.env`, deletes the local temporary file, and never
copies `.env`. Host configuration may include `*_SECRET_ID` references, but not
database passwords, Fernet keys, vendor credentials, cloud keys, or credential
file paths. The first deployment also removes the legacy remote `.env` after the
replacement is safely present.

Airflow resolves `sql_alchemy_conn` and `fernet_key` through the configured
secrets backend. The GCP backend maps them to the two `airflow-config-*` secret
names. Attached identities are the only production authentication path.

## Verification

1. Inspect `runtime_secret_contract` and the per-secret IAM bindings.
2. Run `uv run ctl deploy` with a prohibited key present and verify it refuses
   before contacting a host.
3. Verify `runtime.env` contains references but no secret values.
4. Start each workload with its own identity and verify access succeeds.
5. Attempt cross-role reads (feed to vendor, job to feed, control to both) and
   verify Secret Manager denies them.
6. Search deployment files, Compose output, CI logs, and Terraform state for a
   known canary value before approving production.
