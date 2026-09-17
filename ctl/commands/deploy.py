"""Deploy a tag to a node role.

The single most important property: one SHA is written to one place, and every
role reads it from there. Image drift between the scheduler, the feed and the
batch runner produces failures that look exactly like data bugs.

Provider differences are confined to service activation and ``_update_batch_image``:
GCP hands lifecycle ownership to systemd, while AWS and Azure retain direct
Compose activation.
"""

from __future__ import annotations

import json
import shlex

import typer

from ctl.commands._util import (
    REPO_ROOT,
    capture,
    deployment_env_file,
    detect_cloud,
    eprint,
    load_env,
    resolve_tag,
    sh,
    ssh_target,
)

ROLES = ("control", "feed", "notebook")


def _activate_gcp_service(host: str, role: str) -> None:
    """Enable, restart, and health-gate one baked systemd supervisor."""
    unit = f"jarvis-compose@{role}.service"
    sh(["ssh", host, f"sudo systemctl enable {unit}"])
    sh(["ssh", host, f"sudo systemctl restart {unit}"])
    sh(
        [
            "ssh",
            host,
            f"sudo /usr/local/sbin/jarvis-compose wait {role} 300",
        ]
    )


def _check_database_compatibility(host: str, cloud: str, remote_dir: str) -> None:
    """Prove the candidate control image matches the already-migrated schema."""
    sh(
        [
            "ssh",
            host,
            (
                f"if test -f {remote_dir}/.env.migration-pending; then "
                f"cmp -s {remote_dir}/.env.candidate-tag "
                f"{remote_dir}/.env.migration-pending || "
                "{ echo 'candidate tag differs from pending migration' >&2; exit 1; }; "
                "fi"
            ),
        ]
    )
    if cloud == "gcp":
        sh(
            [
                "ssh",
                host,
                "sudo /usr/local/sbin/jarvis-compose migration-current control",
            ]
        )
        return

    compose_cmd = (
        "compose() { if docker compose version >/dev/null 2>&1; "
        'then docker compose "$@"; else docker-compose "$@"; fi; }; compose'
    )
    flags = (
        f"--env-file {remote_dir}/runtime.env "
        f"--env-file {remote_dir}/.env.candidate-tag "
        f"-f {remote_dir}/compose/control.yml"
    )
    sh(["ssh", host, f"cd {remote_dir} && {compose_cmd} {flags} pull migration"])
    sh(
        [
            "ssh",
            host,
            (
                f"cd {remote_dir} && {compose_cmd} {flags} "
                "run --rm --no-deps migration migration-current"
            ),
        ]
    )


def _compose_files(
    role: str,
    env: dict[str, str],
    remote_dir: str,
    host: str,
) -> list[str]:
    files = [f"{remote_dir}/compose/{role}.yml"]
    if role != "notebook" or not env.get("NOTEBOOKS_HOST_PATH"):
        return files

    notebooks_host_path = env["NOTEBOOKS_HOST_PATH"]
    if not notebooks_host_path.startswith("/"):
        typer.secho(
            "NOTEBOOKS_HOST_PATH must be an absolute path",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    quoted_path = shlex.quote(notebooks_host_path)
    sh(
        [
            "ssh",
            host,
            f"test -d {quoted_path} && mountpoint -q -- {quoted_path}",
        ]
    )
    files.append(f"{remote_dir}/compose/notebook.efs.yml")
    return files


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

    # Build a minimal payload once. The local .env may contain operator-only
    # settings, but it is never copied to a host.
    with deployment_env_file(env) as runtime_env:
        for name in targets:
            host = ssh_target(env, name)
            remote_dir = f"/opt/research/{name}"
            eprint(f"--- deploying {name} @ {host}")

            if cloud == "gcp":
                # GCP's systemd supervisor runs as root. Operators have the
                # equivalent host authority already because managing Docker is
                # root-equivalent, so make that boundary explicit through
                # OS Admin Login and keep deployed files owned by the actor.
                sh(
                    [
                        "ssh",
                        host,
                        (
                            f'sudo install -d -m 0750 -o "$(id -un)" '
                            f'-g "$(id -gn)" {remote_dir} && '
                            f'sudo chown -R "$(id -un):$(id -gn)" {remote_dir}'
                        ),
                    ]
                )
            else:
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
            sh(["rsync", "-az", str(runtime_env), f"{host}:{remote_dir}/runtime.env"])
            # Control remains on its active tag until the candidate proves its
            # schema is current. Other roles do not consume the metadata DB.
            tag_name = ".env.candidate-tag" if name == "control" else ".env.tag"
            quoted_tag = shlex.quote(resolved)
            sh(
                [
                    "ssh",
                    host,
                    f"printf 'IMAGE_TAG=%s\\n' {quoted_tag} > {remote_dir}/{tag_name}",
                ]
            )
            # Remove the legacy full-env payload on the first P2.4 deployment.
            sh(
                [
                    "ssh",
                    host,
                    (
                        f"chmod 600 {remote_dir}/runtime.env {remote_dir}/{tag_name} && "
                        f"rm -f {remote_dir}/.env"
                    ),
                ]
            )

            if name == "control":
                _check_database_compatibility(host, cloud, remote_dir)
                sh(
                    [
                        "ssh",
                        host,
                        (
                            f"mv {remote_dir}/.env.candidate-tag {remote_dir}/.env.tag && "
                            f"chmod 600 {remote_dir}/.env.tag"
                        ),
                    ]
                )

            if cloud == "gcp":
                _activate_gcp_service(host, name)
            else:
                compose_files = _compose_files(name, env, remote_dir, host)
                compose_flags = " ".join(f"-f {shlex.quote(path)}" for path in compose_files)
                env_flags = f"--env-file {remote_dir}/runtime.env --env-file {remote_dir}/.env.tag"
                compose_cmd = (
                    "compose() { if docker compose version >/dev/null 2>&1; "
                    'then docker compose "$@"; else docker-compose "$@"; fi; }; compose'
                )
                sh(
                    [
                        "ssh",
                        host,
                        f"cd {remote_dir} && {compose_cmd} {env_flags} {compose_flags} pull",
                    ]
                )
                sh(
                    [
                        "ssh",
                        host,
                        (
                            f"cd {remote_dir} && {compose_cmd} {env_flags} "
                            f"{compose_flags} up -d --remove-orphans"
                        ),
                    ]
                )
            if name == "control":
                sh(["ssh", host, f"rm -f {remote_dir}/.env.migration-pending"])
            eprint(f"    {name} is on {resolved}")

    if update_batch and ("control" in targets or role == "all"):
        _update_batch_image(env, resolved)

    eprint(f"deployed {resolved} to {', '.join(targets)}", typer.colors.GREEN)
