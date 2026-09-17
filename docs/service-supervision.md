# GCP service supervision

The GCP host image installs one systemd template,
`jarvis-compose@.service`, for the `control`, `feed`, and `notebook` Compose
projects. `ctl deploy` enables the selected instance on its first deployment;
after that, systemd starts it automatically whenever the VM boots.

Systemd is the only lifecycle owner on GCP. A GCP-only Compose override therefore
sets `restart: "no"`; the portable base files retain their recovery policy for
AWS and Azure. The supervisor pulls the selected immutable application tag,
starts the complete project, waits for configured container health checks, and
then checks every service every 30 seconds. Two consecutive unhealthy checks
fail the unit. Systemd waits 20 seconds and retries, but permits only three
starts in five minutes. This recovers ordinary container crashes without an
unbounded crash loop.

The supervisor runs as root because Docker control is root-equivalent. Named
operators therefore receive OS Admin Login, but still receive no Compute Admin
role and can reach SSH only through the port-22 IAP condition. The unit uses
systemd filesystem and kernel protections and stores short-lived Artifact
Registry login material only under `/run/jarvis-ROLE`, which is recreated for
each unit activation. Metadata and Compose network operations have bounded
timeouts. No cloud key or registry token belongs in a deployment env file.

## Deploy and inspect

The normal command copies the non-secret runtime env, tag, and Compose files,
then enables/restarts the unit and waits up to five minutes for JSON health:

```bash
uv run ctl deploy control --tag GIT_SHA
```

Inspect a role over IAP SSH:

```bash
sudo systemctl status jarvis-compose@control.service --no-pager
sudo journalctl -u jarvis-compose@control.service --since=-30m --no-pager
sudo /usr/local/sbin/jarvis-compose health control
```

The health command exits zero only when every expected Compose service exists,
is running, and is either healthy or has no container health check. Its stdout
is one JSON object suitable for automation, for example:

```json
{"schema_version":1,"role":"control","healthy":true,"services":[{"name":"scheduler","state":"running","health":"healthy","healthy":true}]}
```

Use `ctl logs` and `ctl shell` for normal access. Do not run an independent
`docker compose up` on GCP; that creates a second lifecycle owner and bypasses
the restart budget.

## Reboot recovery drill

Run this in development and staging after every supervisor or host-image change:

1. Confirm the health JSON is healthy and record the current image tag.
2. Reboot the VM with the normal cloud operation and wait for OS Login to return.
3. Confirm the unit is `active`, its enablement is `enabled`, health is healthy,
   and the tag is unchanged.
4. Verify the role-specific signal: Airflow scheduler/API health and remote logs,
   feed output freshness, or Jupyter loopback response and notebook storage.
5. Record boot ID, unit activation time, image reference, application tag,
   health JSON, and operator in the change evidence.

## Container-crash recovery drill

In development or staging, select one container ID from
`sudo docker ps --filter label=com.docker.compose.project=jarvis-ROLE --quiet`,
terminate it, and observe the supervisor. Within two health intervals the unit
must fail; systemd then stops the remaining project and starts the complete role
again. Confirm the new container IDs are healthy and the restart counter remains
below the budget.

To test the bound, use an approved non-production configuration that cannot
start, observe the unit reach `failed` after the third start in five minutes,
then restore the valid configuration and run:

```bash
sudo systemctl reset-failed jarvis-compose@ROLE.service
sudo systemctl start jarvis-compose@ROLE.service
sudo /usr/local/sbin/jarvis-compose wait ROLE 300
```

Never run an intentional crash or restart-budget test in production. An
unexpected exhausted budget is an incident: preserve the journal, restore the
last known-good configuration/image, reset the failure state, and verify JSON
health before closing it.

## Notebook and mount behavior

The notebook VM remains stopped when not in use. Once started, its enabled unit
brings Jupyter back automatically. If `NOTEBOOKS_HOST_PATH` is configured, the
supervisor refuses to start unless it is an absolute mounted directory, so an
unavailable shared filesystem cannot silently redirect writes to the boot disk.
Notebook data separation and replacement-host recovery remain P3.6 work.
