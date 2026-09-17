"""Run the candidate image's Airflow metadata migration as one release owner."""

from __future__ import annotations

import re
import shlex

import typer

from ctl.commands._util import (
    REPO_ROOT,
    deployment_env_file,
    detect_cloud,
    eprint,
    load_env,
    resolve_tag,
    sh,
    ssh_target,
)
from ctl.release import resolve_digest


def _remote_compose(remote_dir: str) -> tuple[str, str]:
    command = (
        "compose() { if docker compose version >/dev/null 2>&1; "
        'then docker compose "$@"; else docker-compose "$@"; fi; }; compose'
    )
    flags = (
        f"--env-file {remote_dir}/runtime.env "
        f"--env-file {remote_dir}/.env.migration-tag "
        f"-f {remote_dir}/compose/control.yml"
    )
    return command, flags


def _mark_migration_pending(host: str, remote_dir: str) -> None:
    sh(
        [
            "ssh",
            host,
            (
                f"cp {remote_dir}/.env.migration-tag "
                f"{remote_dir}/.env.migration-pending && "
                f"chmod 600 {remote_dir}/.env.migration-pending"
            ),
        ]
    )


def _run_migration(host: str, cloud: str, remote_dir: str) -> None:
    """Preflight while live, stop control, then run the locked migration."""
    stopped = False
    try:
        if cloud == "gcp":
            sh(
                [
                    "ssh",
                    host,
                    "sudo /usr/local/sbin/jarvis-compose migration-preflight control",
                ]
            )
            sh(["ssh", host, "sudo systemctl stop jarvis-compose@control.service"])
            stopped = True
            _mark_migration_pending(host, remote_dir)
            sh(
                [
                    "ssh",
                    host,
                    "sudo /usr/local/sbin/jarvis-compose migrate control",
                ]
            )
            return

        compose_cmd, flags = _remote_compose(remote_dir)
        sh(["ssh", host, f"cd {remote_dir} && {compose_cmd} {flags} pull migration"])
        sh(
            [
                "ssh",
                host,
                (
                    f"cd {remote_dir} && {compose_cmd} {flags} "
                    "run --rm --no-deps migration migration-preflight"
                ),
            ]
        )
        sh(
            [
                "ssh",
                host,
                f"cd {remote_dir} && {compose_cmd} {flags} stop scheduler api-server",
            ]
        )
        stopped = True
        _mark_migration_pending(host, remote_dir)
        sh(
            [
                "ssh",
                host,
                (
                    f"cd {remote_dir} && {compose_cmd} {flags} "
                    "run --rm --no-deps migration migration"
                ),
            ]
        )
    except typer.Exit:
        if stopped:
            typer.secho(
                "migration failed after control stopped; keep it stopped and follow "
                "the database-migration recovery runbook",
                fg=typer.colors.RED,
            )
        else:
            typer.secho(
                "migration preflight failed; the existing control service was left running",
                fg=typer.colors.RED,
            )
        raise


def migrate(
    tag: str | None = typer.Option(
        None, help="Candidate image tag. Defaults to the short git SHA."
    ),
    backup_reference: str | None = typer.Option(
        None,
        help="Approved pre-migration backup/PITR evidence reference; required in production.",
    ),
    allow_dirty: bool = typer.Option(False, help="Permit using a tag from a dirty tree."),
) -> None:
    """Migrate Airflow metadata with the candidate image, then leave control stopped."""
    env = load_env()
    environment = env.get("RP_ENV", "")
    if environment == "prod" and not backup_reference:
        typer.secho(
            "production migration requires --backup-reference",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    valid_backup_reference = not backup_reference or re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}", backup_reference
    )
    if not valid_backup_reference:
        typer.secho(
            "backup reference must be a 1-256 character identifier",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    cloud = detect_cloud(env)
    if cloud not in {"gcp", "aws", "azure"}:
        typer.secho(f"database migration is unsupported for cloud {cloud!r}", fg=typer.colors.RED)
        raise typer.Exit(1)
    env = {**env, "RP_CLOUD": cloud}

    resolved = resolve_tag(tag, allow_dirty)
    release = resolve_digest(env, resolved)
    host = ssh_target(env, "control")
    remote_dir = "/opt/research/control"
    eprint(f"cloud: {cloud}  migration image: {release.reference(env['IMAGE'])}")
    if backup_reference:
        eprint(f"backup evidence: {backup_reference}")

    with deployment_env_file(env) as runtime_env:
        if cloud == "gcp":
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
        quoted_release = shlex.quote(release.env_text())
        sh(
            [
                "ssh",
                host,
                f"printf %s {quoted_release} > {remote_dir}/.env.migration-tag",
            ]
        )
        sh(
            [
                "ssh",
                host,
                f"chmod 600 {remote_dir}/runtime.env {remote_dir}/.env.migration-tag",
            ]
        )

    _run_migration(host, cloud, remote_dir)
    eprint(
        f"database is current for {release.reference(env['IMAGE'])}; control remains stopped until "
        "that exact tag is deployed",
        typer.colors.GREEN,
    )
