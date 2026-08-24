"""Deploy a tag to a node role.

The single most important property: one SHA is written to one place, and every
role reads it from there. Image drift between the scheduler, the feed and the
batch runner produces failures that look exactly like data bugs.

Provider differences are confined to ``_update_batch_image`` -- everything above
it is the same three rsyncs and a compose restart on all three clouds.
"""

from __future__ import annotations

import json

import typer

from ctl.commands._util import (
    ENV_FILE,
    REPO_ROOT,
    capture,
    detect_cloud,
    eprint,
    load_env,
    resolve_tag,
    sh,
    ssh_target,
)

ROLES = ("control", "feed", "notebook")


def _update_batch_image(env: dict[str, str], tag: str) -> None:
    """Point the batch job definition at ``tag``.

    Each provider models "the thing a task runs in" differently:
      GCP    a Cloud Run Job, updated in place
      AWS    a Batch job definition, which is immutable -- registering a new
             revision is the update, and the operator picks up the latest
      Azure  Container Instances have no persistent definition at all, so the
             tag travels in the control node's env file instead
    """
    cloud = detect_cloud(env)
    image = env["IMAGE"]

    if cloud == "gcp":
        sh(
            [
                "gcloud",
                "run",
                "jobs",
                "update",
                env.get("RP_BATCH_JOB_NAME", "research-job"),
                "--image",
                f"{image}:{tag}",
                "--region",
                env["RP_REGION"],
                "--project",
                env["RP_PROJECT_ID"],
            ]
        )
    elif cloud == "aws":
        name = env.get("RP_BATCH_JOB_NAME", "research-job")
        current = json.loads(
            capture(
                [
                    "aws",
                    "batch",
                    "describe-job-definitions",
                    "--job-definition-name",
                    name,
                    "--status",
                    "ACTIVE",
                    "--region",
                    env["RP_REGION"],
                    "--query",
                    "sort_by(jobDefinitions,&revision)[-1]",
                    "--output",
                    "json",
                ]
            )
        )
        if not current:
            raise RuntimeError(f"no active AWS Batch job definition named {name!r}")
        # Registration rejects server-owned response fields. Preserve all
        # functional settings from Terraform and change only the image.
        for key in (
            "jobDefinitionArn",
            "revision",
            "status",
            "containerOrchestrationType",
            "ecsProperties",
            "eksProperties",
            "nodeProperties",
        ):
            current.pop(key, None)
        current["containerProperties"]["image"] = f"{image}:{tag}"
        sh(
            [
                "aws",
                "batch",
                "register-job-definition",
                "--region",
                env["RP_REGION"],
                "--cli-input-json",
                json.dumps(current, separators=(",", ":")),
            ]
        )
    elif cloud == "azure":
        eprint(
            "    azure: ACI has no persistent job definition; the tag ships in "
            "the control node env file (already written above)."
        )
    else:
        eprint(f"    unknown cloud {cloud!r}; skipping batch image update", typer.colors.YELLOW)


def deploy(
    role: str = typer.Argument(..., help=f"One of: {', '.join(ROLES)}, or 'all'."),
    tag: str | None = typer.Option(
        None, help="Image tag to deploy. Defaults to the short git SHA."
    ),
    allow_dirty: bool = typer.Option(False, help="Permit deploying from a dirty tree."),
    update_batch: bool = typer.Option(
        True, help="Also point the batch job definition at this tag."
    ),
) -> None:
    """Ship compose files and the pinned tag to a node, then restart it."""
    env = load_env()
    resolved = resolve_tag(tag, allow_dirty)
    targets = ROLES if role == "all" else (role,)

    for name in targets:
        if name not in ROLES:
            typer.secho(f"unknown role {name!r}", fg=typer.colors.RED)
            raise typer.Exit(1)

    cloud = detect_cloud(env)
    eprint(f"cloud: {cloud}  tag: {resolved}")

    for name in targets:
        host = ssh_target(env, name)
        remote_dir = f"/opt/research/{name}"
        eprint(f"--- deploying {name} @ {host}")

        sh(["ssh", host, f"mkdir -p {remote_dir}"])
        sh(
            [
                "rsync",
                "-az",
                "--delete",
                str(REPO_ROOT / "compose") + "/",
                f"{host}:{remote_dir}/compose/",
            ]
        )
        sh(["rsync", "-az", str(ENV_FILE), f"{host}:{remote_dir}/.env"])
        # The one place the tag is written.
        sh(["ssh", host, f"printf 'IMAGE_TAG={resolved}\\n' > {remote_dir}/.env.tag"])

        compose = f"{remote_dir}/compose/{name}.yml"
        env_flags = f"--env-file {remote_dir}/.env --env-file {remote_dir}/.env.tag"
        compose_cmd = (
            "compose() { if docker compose version >/dev/null 2>&1; "
            'then docker compose "$@"; else docker-compose "$@"; fi; }; compose'
        )
        sh(["ssh", host, f"cd {remote_dir} && {compose_cmd} {env_flags} -f {compose} pull"])
        sh(
            [
                "ssh",
                host,
                f"cd {remote_dir} && {compose_cmd} {env_flags} -f {compose} up -d --remove-orphans",
            ]
        )
        eprint(f"    {name} is on {resolved}")

    if update_batch and ("control" in targets or role == "all"):
        _update_batch_image(env, resolved)

    eprint(f"deployed {resolved} to {', '.join(targets)}", typer.colors.GREEN)
