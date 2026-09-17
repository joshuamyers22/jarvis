"""Open a shell in a running container, or in a fresh one locally."""

from __future__ import annotations

import typer

from ctl.commands._util import (
    ENV_FILE,
    detect_cloud,
    load_env,
    resolve_tag,
    sh,
    ssh_target,
)


def shell(
    role: str = typer.Argument("local", help="control | feed | notebook | local"),
    service: str | None = typer.Option(None, help="Compose service. Defaults per role."),
    tag: str | None = typer.Option(None, help="For 'local', the tag to run."),
) -> None:
    """Interactive shell in the platform image."""
    env = load_env()

    if role == "local":
        resolved = resolve_tag(tag, allow_dirty=True)
        sh(
            [
                "docker",
                "run",
                "--rm",
                "-it",
                "--env-file",
                str(ENV_FILE),
                f"{env['IMAGE']}:{resolved}",
                "bash",
            ],
            check=False,
        )
        return

    default_service = {"control": "scheduler", "feed": "feed", "notebook": "jupyter"}
    target = service or default_service.get(role, role)
    host = ssh_target(env, role)
    remote_dir = f"/opt/research/{role}"
    compose = f"{remote_dir}/compose/{role}.yml"
    gcp = detect_cloud(env) == "gcp"
    sudo = "sudo " if gcp else ""
    project = f"--project-name jarvis-{role} " if gcp else ""
    compose_cmd = (
        f"compose() {{ if {sudo}docker compose version >/dev/null 2>&1; "
        f'then {sudo}docker compose "$@"; else {sudo}docker-compose "$@"; fi; }}; compose'
    )

    sh(
        [
            "ssh",
            "-t",
            host,
            f"cd {remote_dir} && {compose_cmd} {project}--env-file {remote_dir}/runtime.env "
            f"--env-file {remote_dir}/.env.tag -f {compose} exec {target} bash",
        ],
        check=False,
    )
