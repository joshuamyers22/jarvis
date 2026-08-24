"""Run a job -- locally, or as a one-off batch execution."""

from __future__ import annotations

import typer

from ctl.commands._util import ENV_FILE, detect_cloud, eprint, load_env, resolve_tag, sh


def run(
    module: str = typer.Argument(..., help="Job module name, e.g. pull_ohlcv"),
    date: str = typer.Option(..., "--date", help="Logical date, YYYY-MM-DD."),
    remote: bool = typer.Option(False, help="Execute on the batch service instead of locally."),
    force: bool = typer.Option(False, help="Recompute even if the partition is complete."),
    tag: str | None = typer.Option(None, help="Image tag. Defaults to the short git SHA."),
) -> None:
    """Run one job. The same command works before and after a DAG exists for it."""
    env = load_env()
    args = ["job", module, "--date", date] + (["--force"] if force else [])

    if remote:
        cloud = detect_cloud(env)
        job = env.get("RP_BATCH_JOB_NAME", "research-job")
        if cloud == "gcp":
            sh(
                [
                    "gcloud",
                    "run",
                    "jobs",
                    "execute",
                    job,
                    "--region",
                    env["RP_REGION"],
                    "--project",
                    env["RP_PROJECT_ID"],
                    "--args",
                    ",".join(args),
                    "--wait",
                ]
            )
        elif cloud == "aws":
            import json

            sh(
                [
                    "aws",
                    "batch",
                    "submit-job",
                    "--job-name",
                    f"{job}-{module}-{date}",
                    "--job-definition",
                    job,
                    "--job-queue",
                    env["RP_BATCH_JOB_QUEUE"],
                    "--region",
                    env["RP_REGION"],
                    "--container-overrides",
                    json.dumps({"command": args}),
                ]
            )
        elif cloud == "azure":
            resolved_tag = resolve_tag(tag, allow_dirty=True)
            sh(
                [
                    "az",
                    "container",
                    "create",
                    "--resource-group",
                    env["RP_RESOURCE_GROUP"],
                    "--name",
                    f"rp-{module}-{date.replace('-', '')}",
                    "--image",
                    f"{env['IMAGE']}:{resolved_tag}",
                    "--restart-policy",
                    "Never",
                    "--command-line",
                    " ".join(args),
                ]
            )
        else:
            eprint(f"cannot run remotely on cloud={cloud!r}")
        return

    resolved = resolve_tag(tag, allow_dirty=True)
    eprint(f"running jobs.{module} for {date} locally on {resolved}")
    sh(
        ["docker", "run", "--rm", "--env-file", str(ENV_FILE), f"{env['IMAGE']}:{resolved}", *args],
    )
