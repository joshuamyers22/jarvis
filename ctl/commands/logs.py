"""Tail logs from a node."""

from __future__ import annotations

import typer

from ctl.commands._util import detect_cloud, load_env, sh, ssh_target


def logs(
    role: str = typer.Argument(..., help="control | feed | notebook"),
    service: str | None = typer.Option(None, help="Restrict to one compose service."),
    lines: int = typer.Option(200, "--lines", "-n", help="Lines of history."),
    follow: bool = typer.Option(True, help="Keep streaming."),
) -> None:
    """Stream container logs over SSH."""
    env = load_env()
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
    command = (
        f"cd {remote_dir} && {compose_cmd} {project}--env-file {remote_dir}/runtime.env "
        f"--env-file {remote_dir}/.env.tag -f {compose} logs --tail {lines}"
    )
    if follow:
        command += " -f"
    if service:
        command += f" {service}"

    sh(["ssh", "-t", host, command], check=False)
