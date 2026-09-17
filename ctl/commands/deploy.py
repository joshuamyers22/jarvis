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
import re
import shlex
import subprocess
from datetime import UTC, datetime

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
from ctl.configuration import ConfigurationError, require_current_configuration
from ctl.release import Release, parse_release_env, resolve_digest

ROLES = ("control", "feed", "notebook")
AWS_EFS_ID_PATTERN = re.compile(r"fs-[0-9a-f]{8,40}")
AWS_EFS_ACCESS_POINT_PATTERN = re.compile(r"fsap-[0-9a-f]{8,40}")


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

    compose_cmd, flags = _portable_compose(
        remote_dir, "control", ".env.candidate-tag", candidate=True
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


def _check_active_database_compatibility(host: str, cloud: str, remote_dir: str) -> None:
    """Prove the currently active control image matches the database schema."""
    if cloud == "gcp":
        sh(
            [
                "ssh",
                host,
                "sudo /usr/local/sbin/jarvis-compose schema-current control",
            ]
        )
        return
    compose_cmd, flags = _portable_compose(remote_dir, "control", ".env.tag")
    sh(["ssh", host, f"cd {remote_dir} && {compose_cmd} {flags} pull migration"])
    sh(
        [
            "ssh",
            host,
            f"cd {remote_dir} && {compose_cmd} {flags} "
            "run --rm --no-deps migration migration-current",
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

    storage_mode = env.get("RP_NOTEBOOK_STORAGE_MODE")
    storage_id = env.get("RP_NOTEBOOK_STORAGE_ID", "")
    quoted_path = shlex.quote(notebooks_host_path)
    if storage_mode == "gcp-pd":
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", storage_id):
            typer.secho("invalid GCP notebook storage ID", fg=typer.colors.RED)
            raise typer.Exit(1)
        sh(
            [
                "ssh",
                host,
                f"sudo /usr/local/sbin/jarvis-notebook-storage verify {quoted_path}",
            ]
        )
    elif storage_mode == "aws-efs":
        access_point = env.get("RP_NOTEBOOK_STORAGE_ACCESS_POINT_ID", "")
        if not AWS_EFS_ID_PATTERN.fullmatch(
            storage_id
        ) or not AWS_EFS_ACCESS_POINT_PATTERN.fullmatch(access_point):
            typer.secho("invalid AWS EFS notebook storage identifiers", fg=typer.colors.RED)
            raise typer.Exit(1)
        awk_program = (
            '$1 == source && $2 == target && $3 == "efs" { '
            'tls=0; iam=0; ap=0; count=split($4, options, ","); '
            "for (i=1; i<=count; i++) { "
            'if (options[i] == "tls") tls=1; '
            'if (options[i] == "iam") iam=1; '
            "if (options[i] == access_point) ap=1; } "
            "if (tls && iam && ap) valid=1 } END { exit(valid ? 0 : 1) }"
        )
        command = (
            f"test -d {quoted_path} && mountpoint -q -- {quoted_path} && "
            f"findmnt -n -t nfs4 --target {quoted_path} >/dev/null && "
            "sudo awk "
            f"-v source={shlex.quote(storage_id + ':/')} "
            f"-v target={quoted_path} "
            f"-v access_point={shlex.quote('accesspoint=' + access_point)} "
            f"{shlex.quote(awk_program)} /etc/fstab"
        )
        sh(["ssh", host, command])
    else:
        typer.secho(
            "NOTEBOOKS_HOST_PATH requires a supported RP_NOTEBOOK_STORAGE_MODE",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    files.append(f"{remote_dir}/compose/notebook.storage.yml")
    return files


def _update_batch_image(env: dict[str, str], release: Release) -> None:
    """Point the batch job definition at one immutable release.

    Each provider models "the thing a task runs in" differently:
      GCP    a Cloud Run Job, updated in place
      AWS    a Batch job definition, which is immutable -- registering a new
             revision is the update, and the operator picks up the latest
      Azure  Container Instances have no persistent definition at all, so the
             tag travels in the control node's env file instead
    """
    cloud = detect_cloud(env)
    image = env["IMAGE"]
    image_reference = release.reference(image)

    if cloud == "gcp":
        sh(
            [
                "gcloud",
                "run",
                "jobs",
                "update",
                env.get("RP_BATCH_JOB_NAME", "research-job"),
                "--image",
                image_reference,
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
        current["containerProperties"]["image"] = image_reference
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


def _write_release_file(host: str, path: str, release: Release) -> None:
    payload = shlex.quote(release.env_text())
    sh(["ssh", host, f"printf %s {payload} > {path} && chmod 600 {path}"])


def _read_release_file(host: str, path: str) -> Release | None:
    try:
        value = capture(["ssh", host, f"test -f {path} && cat {path}"])
    except subprocess.CalledProcessError:
        return None
    try:
        return parse_release_env(value)
    except ValueError:
        typer.secho(f"invalid remote release file: {host}:{path}", fg=typer.colors.RED)
        raise typer.Exit(1) from None


def _portable_compose(
    remote_dir: str, role: str, tag_file: str, *, candidate: bool = False
) -> tuple[str, str]:
    compose_cmd = (
        "compose() { if docker compose version >/dev/null 2>&1; "
        'then docker compose "$@"; else docker-compose "$@"; fi; }; compose'
    )
    runtime = "runtime.candidate.env" if candidate else "runtime.env"
    compose_dir = "compose.candidate" if candidate else "compose"
    flags = (
        f"--env-file {remote_dir}/{runtime} --env-file {remote_dir}/{tag_file} "
        f"-f {remote_dir}/{compose_dir}/{role}.yml"
    )
    return compose_cmd, flags


def _preflight_candidate(
    host: str,
    role: str,
    cloud: str,
    env: dict[str, str],
    release: Release,
) -> None:
    """Pull the exact digest and prove that its provider matches the target."""
    remote_dir = f"/opt/research/{role}"
    if cloud == "gcp":
        sh(["ssh", host, f"sudo /usr/local/sbin/jarvis-compose candidate-preflight {role}"])
        return

    compose_cmd, flags = _portable_compose(remote_dir, role, ".env.candidate-tag", candidate=True)
    image_reference = shlex.quote(release.reference(env["IMAGE"]))
    expected_cloud = shlex.quote(cloud)
    sh(["ssh", host, f"cd {remote_dir} && {compose_cmd} {flags} config --quiet"])
    sh(["ssh", host, f"cd {remote_dir} && {compose_cmd} {flags} pull"])
    sh(
        [
            "ssh",
            host,
            (
                'test "$(docker image inspect --format '
                "'{{range .Config.Env}}{{println .}}{{end}}' "
                f"{image_reference} | sed -n 's/^RP_IMAGE_CLOUD=//p')\" = {expected_cloud}"
            ),
        ]
    )


def _activate_role(host: str, role: str, cloud: str, env: dict[str, str]) -> None:
    remote_dir = f"/opt/research/{role}"
    if cloud == "gcp":
        _activate_gcp_service(host, role)
        return
    compose_files = _compose_files(role, env, remote_dir, host)
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
            (
                f"cd {remote_dir} && {compose_cmd} {env_flags} {compose_flags} "
                "up -d --remove-orphans --wait --wait-timeout 300"
            ),
        ]
    )


def _verify_remote_logs(host: str, role: str, cloud: str) -> None:
    """Prove release logs are remotely retrievable before reporting success."""
    remote_dir = f"/opt/research/{role}"
    if cloud == "gcp":
        sh(
            [
                "ssh",
                host,
                f"sudo journalctl -u jarvis-compose@{role}.service -n 20 --no-pager --quiet",
            ]
        )
        return
    compose_cmd, flags = _portable_compose(remote_dir, role, ".env.tag")
    sh(["ssh", host, f"cd {remote_dir} && {compose_cmd} {flags} logs --tail 20"])


def _collect_failure_logs(host: str, role: str, cloud: str) -> None:
    typer.secho(f"--- failure logs for {role} @ {host}", fg=typer.colors.YELLOW)
    if cloud == "gcp":
        sh(
            [
                "ssh",
                host,
                f"sudo journalctl -u jarvis-compose@{role}.service -n 200 --no-pager",
            ],
            check=False,
        )
        return
    remote_dir = f"/opt/research/{role}"
    compose_cmd, flags = _portable_compose(remote_dir, role, ".env.tag")
    sh(
        ["ssh", host, f"cd {remote_dir} && {compose_cmd} {flags} logs --tail 200"],
        check=False,
    )


def _promote_candidate(host: str, role: str) -> bool:
    remote_dir = f"/opt/research/{role}"
    previous = _read_release_file(host, f"{remote_dir}/.env.tag") is not None
    if previous:
        prefix = (
            f"rm -rf {remote_dir}/compose.previous && "
            f"rm -f {remote_dir}/runtime.previous.env && "
            f"mv {remote_dir}/compose {remote_dir}/compose.previous && "
            f"mv {remote_dir}/runtime.env {remote_dir}/runtime.previous.env && "
            f"cp {remote_dir}/.env.tag {remote_dir}/.env.previous-tag && "
        )
    else:
        prefix = (
            f"rm -rf {remote_dir}/compose {remote_dir}/compose.previous && "
            f"rm -f {remote_dir}/runtime.previous.env {remote_dir}/.env.previous-tag && "
        )
    sh(
        [
            "ssh",
            host,
            (
                f"{prefix}mv {remote_dir}/compose.candidate {remote_dir}/compose && "
                f"mv {remote_dir}/runtime.candidate.env {remote_dir}/runtime.env && "
                f"mv {remote_dir}/.env.candidate-tag {remote_dir}/.env.tag && "
                f"chmod 600 {remote_dir}/runtime.env {remote_dir}/.env.tag"
            ),
        ]
    )
    return previous


def _stage_previous_candidate(host: str, role: str) -> None:
    remote_dir = f"/opt/research/{role}"
    sh(
        [
            "ssh",
            host,
            (
                f"test -d {remote_dir}/compose.previous && "
                f"test -f {remote_dir}/runtime.previous.env && "
                f"rm -rf {remote_dir}/compose.candidate && "
                f"cp -a {remote_dir}/compose.previous {remote_dir}/compose.candidate && "
                f"cp {remote_dir}/runtime.previous.env {remote_dir}/runtime.candidate.env && "
                f"cp {remote_dir}/.env.previous-tag {remote_dir}/.env.candidate-tag && "
                f"chmod 600 {remote_dir}/runtime.candidate.env "
                f"{remote_dir}/.env.candidate-tag"
            ),
        ]
    )


def _rollback_role(host: str, role: str, cloud: str, env: dict[str, str]) -> Release:
    """Swap active and previous releases, compatibility-checking control first."""
    remote_dir = f"/opt/research/{role}"
    previous = _read_release_file(host, f"{remote_dir}/.env.previous-tag")
    if previous is None:
        raise RuntimeError(f"{role} has no previous release")

    _stage_previous_candidate(host, role)
    _preflight_candidate(host, role, cloud, env, previous)
    if role == "control":
        _check_database_compatibility(host, cloud, remote_dir)
    _promote_candidate(host, role)
    try:
        _activate_role(host, role, cloud, env)
        _verify_remote_logs(host, role, cloud)
    except (typer.Exit, RuntimeError):
        _collect_failure_logs(host, role, cloud)
        _stage_previous_candidate(host, role)
        _promote_candidate(host, role)
        try:
            _activate_role(host, role, cloud, env)
        except (typer.Exit, RuntimeError):
            typer.secho(
                f"failed to restore {role} after rollback activation failed",
                fg=typer.colors.RED,
            )
        raise
    return previous


def _stop_role(host: str, role: str, cloud: str) -> None:
    if cloud == "gcp":
        sh(["ssh", host, f"sudo systemctl stop jarvis-compose@{role}.service"], check=False)
    else:
        remote_dir = f"/opt/research/{role}"
        compose_cmd, flags = _portable_compose(remote_dir, role, ".env.tag")
        sh(["ssh", host, f"cd {remote_dir} && {compose_cmd} {flags} down"], check=False)


def _rollback_or_stop(host: str, role: str, cloud: str, env: dict[str, str]) -> None:
    if _read_release_file(host, f"/opt/research/{role}/.env.previous-tag") is None:
        _stop_role(host, role, cloud)
        typer.secho(f"{role} stopped: no previous release exists", fg=typer.colors.RED)
        return
    restored = _rollback_role(host, role, cloud, env)
    eprint(f"    rolled {role} back to {restored.reference(env['IMAGE'])}", typer.colors.YELLOW)


def _run_synthetic_probe(env: dict[str, str], release: Release, release_id: str) -> None:
    cloud = detect_cloud(env)
    job = env.get("RP_BATCH_JOB_NAME", "research-job")
    args = ["release-probe", "--release-id", release_id, "--expected-cloud", cloud]
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
        job_id = capture(
            [
                "aws",
                "batch",
                "submit-job",
                "--job-name",
                f"jarvis-release-{release_id}",
                "--job-definition",
                job,
                "--job-queue",
                env["RP_BATCH_JOB_QUEUE"],
                "--region",
                env["RP_REGION"],
                "--container-overrides",
                json.dumps({"command": args}, separators=(",", ":")),
                "--query",
                "jobId",
                "--output",
                "text",
            ]
        )
        sh(
            [
                "aws",
                "batch",
                "wait",
                "jobs-complete",
                "--jobs",
                job_id,
                "--region",
                env["RP_REGION"],
            ]
        )
        status = capture(
            [
                "aws",
                "batch",
                "describe-jobs",
                "--jobs",
                job_id,
                "--region",
                env["RP_REGION"],
                "--query",
                "jobs[0].status",
                "--output",
                "text",
            ]
        )
        if status != "SUCCEEDED":
            raise RuntimeError(f"synthetic AWS Batch job ended in {status}")
    elif cloud == "azure":
        name = f"jarvis-release-{release_id}".lower()[:63].rstrip("-")
        sh(
            [
                "az",
                "container",
                "create",
                "--resource-group",
                env["RP_RESOURCE_GROUP"],
                "--name",
                name,
                "--image",
                release.reference(env["IMAGE"]),
                "--restart-policy",
                "Never",
                "--command-line",
                " ".join(args),
            ]
        )
        sh(
            [
                "az",
                "container",
                "wait",
                "--resource-group",
                env["RP_RESOURCE_GROUP"],
                "--name",
                name,
                "--custom",
                "containers[0].instanceView.currentState.state=='Terminated'",
            ]
        )
        exit_code = capture(
            [
                "az",
                "container",
                "show",
                "--resource-group",
                env["RP_RESOURCE_GROUP"],
                "--name",
                name,
                "--query",
                "containers[0].instanceView.currentState.exitCode",
                "--output",
                "tsv",
            ]
        )
        if exit_code != "0":
            raise RuntimeError(f"synthetic Azure container exited {exit_code}")
    else:
        raise RuntimeError(f"synthetic probe is unsupported for cloud {cloud!r}")


def _record_release_evidence(
    env: dict[str, str], targets: tuple[str, ...], release: Release, release_id: str
) -> None:
    payload = release.env_text() + f"RELEASE_ID={release_id}\n"
    if fingerprint := env.get("RP_CONFIG_FINGERPRINT"):
        payload += f"RP_CONFIG_FINGERPRINT={fingerprint}\n"
    quoted = shlex.quote(payload)
    for role in targets:
        host = ssh_target(env, role)
        path = f"/opt/research/{role}/.release-evidence"
        sh(["ssh", host, f"printf %s {quoted} > {path} && chmod 600 {path}"])


def deploy(
    role: str = typer.Argument(..., help=f"One of: {', '.join(ROLES)}, or 'all'."),
    tag: str | None = typer.Option(
        None, help="Image tag to deploy. Defaults to the short git SHA."
    ),
    allow_dirty: bool = typer.Option(False, help="Permit deploying from a dirty tree."),
    update_batch: bool = typer.Option(
        True, help="Also point the batch job definition at this tag."
    ),
    synthetic: bool = typer.Option(
        True,
        "--synthetic/--skip-synthetic",
        help="Run the candidate batch image through a scratch-storage write/read probe.",
    ),
) -> None:
    """Health-gate an immutable release and roll back the whole transaction on failure."""
    env = load_env()
    try:
        require_current_configuration(env, refresh_terraform=True)
    except ConfigurationError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None
    targets = ROLES if role == "all" else (role,)

    for name in targets:
        if name not in ROLES:
            typer.secho(f"unknown role {name!r}", fg=typer.colors.RED)
            raise typer.Exit(1)

    cloud = detect_cloud(env)
    if cloud not in {"gcp", "aws", "azure"}:
        typer.secho(f"deployment is unsupported for cloud {cloud!r}", fg=typer.colors.RED)
        raise typer.Exit(1)
    env = {**env, "RP_CLOUD": cloud}
    required = {"IMAGE", "RP_ENV", "RP_STORAGE_URI"}
    required |= {
        "gcp": {"RP_PROJECT_ID", "RP_REGION"},
        "aws": {"RP_REGION"},
        "azure": {"RP_RESOURCE_GROUP"},
    }[cloud]
    if "control" in targets and synthetic:
        required.add("RP_SCRATCH_URI")
    if "control" in targets and update_batch and cloud == "aws":
        required.add("RP_BATCH_JOB_QUEUE")
    missing = sorted(key for key in required if not env.get(key))
    if missing:
        typer.secho(
            "missing deployment settings: " + ", ".join(missing),
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    hosts = {name: ssh_target(env, name) for name in targets}
    if env.get("RP_ENV") == "prod" and "control" in targets and (not update_batch or not synthetic):
        typer.secho(
            "production control deployment requires batch update and synthetic output",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    resolved = resolve_tag(tag, allow_dirty)
    release = resolve_digest(env, resolved)
    release_id = f"{env.get('RP_ENV', 'unknown')}-{resolved[:64]}-{datetime.now(UTC):%Y%m%d%H%M%S}"
    eprint(f"cloud: {cloud}  image: {release.reference(env['IMAGE'])}")

    prior_batch_release: Release | None = None
    if update_batch and "control" in targets:
        control_host = hosts["control"]
        prior_batch_release = _read_release_file(control_host, "/opt/research/control/.env.tag")

    activated: list[tuple[str, str]] = []

    # Build a minimal payload once. The local .env may contain operator-only
    # settings, but it is never copied to a host.
    try:
        with deployment_env_file(env) as runtime_env:
            for name in targets:
                host = hosts[name]
                remote_dir = f"/opt/research/{name}"
                eprint(f"--- candidate {name} @ {host}")

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
                        f"{host}:{remote_dir}/compose.candidate/",
                    ]
                )
                sh(
                    [
                        "rsync",
                        "-az",
                        str(runtime_env),
                        f"{host}:{remote_dir}/runtime.candidate.env",
                    ]
                )
                _write_release_file(host, f"{remote_dir}/.env.candidate-tag", release)
                sh(["ssh", host, f"rm -f {remote_dir}/.env"])

                _preflight_candidate(host, name, cloud, env, release)
                if name == "control":
                    _check_database_compatibility(host, cloud, remote_dir)
                _promote_candidate(host, name)
                try:
                    _activate_role(host, name, cloud, env)
                    _verify_remote_logs(host, name, cloud)
                except (typer.Exit, RuntimeError):
                    _collect_failure_logs(host, name, cloud)
                    _rollback_or_stop(host, name, cloud, env)
                    raise
                activated.append((name, host))
                eprint(f"    {name} passed health and log gates")

        if update_batch and "control" in targets:
            _update_batch_image(env, release)
            if synthetic:
                _run_synthetic_probe(env, release, release_id)
        if "control" in targets:
            sh(
                [
                    "ssh",
                    hosts["control"],
                    "rm -f /opt/research/control/.env.migration-pending",
                ]
            )
        _record_release_evidence(env, targets, release, release_id)
    except Exception:
        typer.secho("release transaction failed; restoring activated roles", fg=typer.colors.RED)
        if update_batch and "control" in targets and prior_batch_release is not None:
            try:
                _update_batch_image(env, prior_batch_release)
            except Exception:
                typer.secho("batch rollback failed; operator action required", fg=typer.colors.RED)
        for name, host in reversed(activated):
            try:
                _rollback_or_stop(host, name, cloud, env)
            except Exception:
                typer.secho(
                    f"rollback failed for {name}; operator action required", fg=typer.colors.RED
                )
        raise typer.Exit(1) from None

    eprint(
        f"deployed {release.reference(env['IMAGE'])} to {', '.join(targets)}; "
        f"release evidence {release_id}",
        typer.colors.GREEN,
    )
