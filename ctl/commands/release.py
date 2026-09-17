"""Plan, inspect, diagnose, and roll back immutable deployments."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime

import typer

from ctl.commands import deploy as deployment
from ctl.commands._util import capture, detect_cloud, eprint, load_env, resolve_tag, ssh_target
from ctl.configuration import (
    ConfigurationError,
    ConfigurationStatus,
    configured_status,
    require_current_configuration,
)
from ctl.release import Release, parse_release_env, resolve_digest


def _targets(role: str) -> tuple[str, ...]:
    targets = deployment.ROLES if role == "all" else (role,)
    if any(item not in deployment.ROLES for item in targets):
        typer.secho(f"unknown role {role!r}", fg=typer.colors.RED)
        raise typer.Exit(1)
    return targets


def _health(env: dict[str, str], role: str) -> tuple[dict[str, object], str]:
    cloud = detect_cloud(env)
    host = ssh_target(env, role)
    remote_dir = f"/opt/research/{role}"
    if cloud == "gcp":
        output = capture(["ssh", host, f"sudo /usr/local/sbin/jarvis-compose health {role}"])
        health = json.loads(output)
        image = capture(
            ["ssh", host, f"sudo /usr/local/sbin/jarvis-compose image-reference {role}"]
        )
        return health, image

    compose_cmd, flags = deployment._portable_compose(remote_dir, role, ".env.tag")
    output = capture(
        [
            "ssh",
            host,
            f"cd {remote_dir} && {compose_cmd} {flags} ps --all --format json",
        ]
    )
    current = deployment._read_release_file(host, f"{remote_dir}/.env.tag")
    image = current.reference(env["IMAGE"]) if current else ""
    return {"schema_version": 1, "role": role, "healthy": True, "services": output}, image


def _local_configuration_status(
    env: dict[str, str], *, refresh_terraform: bool
) -> ConfigurationStatus | None:
    if not env.get("RP_CONFIG_FILE") and env.get("RP_ENV") != "prod":
        return None
    return configured_status(env, refresh_terraform=refresh_terraform)


def _remote_configuration_fingerprint(env: dict[str, str], role: str) -> str | None:
    if not env.get("RP_CONFIG_FINGERPRINT"):
        return None
    host = ssh_target(env, role)
    try:
        value = capture(
            [
                "ssh",
                host,
                f"test -f /opt/research/{role}/runtime.env && "
                f"sed -n 's/^RP_CONFIG_FINGERPRINT=//p' "
                f"/opt/research/{role}/runtime.env",
            ]
        )
    except subprocess.CalledProcessError:
        return None
    return value or None


def _release_status(env: dict[str, str], role: str) -> dict[str, object]:
    host = ssh_target(env, role)
    remote_dir = f"/opt/research/{role}"
    current = deployment._read_release_file(host, f"{remote_dir}/.env.tag")
    previous = deployment._read_release_file(host, f"{remote_dir}/.env.previous-tag")
    if current is None:
        return {"role": role, "host": host, "healthy": False, "error": "not-deployed"}
    try:
        health, actual_image = _health(env, role)
        expected_image = current.reference(env["IMAGE"])
        expected_configuration = env.get("RP_CONFIG_FINGERPRINT")
        actual_configuration = _remote_configuration_fingerprint(env, role)
        configuration_current = (
            expected_configuration is None or actual_configuration == expected_configuration
        )
        healthy = (
            bool(health.get("healthy")) and actual_image == expected_image and configuration_current
        )
        return {
            "role": role,
            "host": host,
            "release": {"tag": current.tag, "digest": current.digest},
            "previous": (
                {"tag": previous.tag, "digest": previous.digest} if previous is not None else None
            ),
            "expected_image": expected_image,
            "actual_image": actual_image,
            "expected_configuration": expected_configuration,
            "actual_configuration": actual_configuration,
            "configuration_current": configuration_current,
            "healthy": healthy,
            "health": health,
        }
    except (subprocess.CalledProcessError, json.JSONDecodeError, ValueError) as exc:
        return {
            "role": role,
            "host": host,
            "release": {"tag": current.tag, "digest": current.digest},
            "healthy": False,
            "error": type(exc).__name__,
        }


def plan(
    role: str = typer.Argument("all", help="control | feed | notebook | all"),
    tag: str | None = typer.Option(None, help="Candidate tag; defaults to the short git SHA."),
    allow_dirty: bool = typer.Option(False, help="Permit planning from a dirty tree."),
) -> None:
    """Resolve the candidate digest and show the remote changes without applying them."""
    env = load_env()
    try:
        configuration = require_current_configuration(env, refresh_terraform=True)
    except ConfigurationError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None
    cloud = detect_cloud(env)
    if cloud not in {"gcp", "aws", "azure"}:
        typer.secho(f"deployment is unsupported for cloud {cloud!r}", fg=typer.colors.RED)
        raise typer.Exit(1)
    candidate = resolve_digest(env, resolve_tag(tag, allow_dirty))
    changes = []
    for name in _targets(role):
        host = ssh_target(env, name)
        current = deployment._read_release_file(host, f"/opt/research/{name}/.env.tag")
        changes.append(
            {
                "role": name,
                "host": host,
                "current": (
                    {"tag": current.tag, "digest": current.digest} if current is not None else None
                ),
                "action": "no-op" if current == candidate else "deploy",
            }
        )
    typer.echo(
        json.dumps(
            {
                "schema_version": 1,
                "environment": env.get("RP_ENV", ""),
                "provider": cloud,
                "candidate": {"tag": candidate.tag, "digest": candidate.digest},
                "image": candidate.reference(env["IMAGE"]),
                "configuration": configuration.as_dict() if configuration else None,
                "changes": changes,
            },
            indent=2,
            sort_keys=True,
        )
    )


def status(
    role: str = typer.Argument("all", help="control | feed | notebook | all"),
) -> None:
    """Report desired and running digest, health, and rollback availability."""
    env = load_env()
    configuration = _local_configuration_status(env, refresh_terraform=True)
    results = [_release_status(env, name) for name in _targets(role)]
    typer.echo(
        json.dumps(
            {
                "schema_version": 1,
                "configuration": configuration.as_dict() if configuration else None,
                "roles": results,
            },
            indent=2,
            sort_keys=True,
        )
    )
    if (configuration is not None and not configuration.current) or not all(
        item.get("healthy") is True for item in results
    ):
        raise typer.Exit(1)


def _evidence_matches(env: dict[str, str], role: str, release: Release) -> bool:
    host = ssh_target(env, role)
    try:
        value = capture(
            [
                "ssh",
                host,
                f"test -f /opt/research/{role}/.release-evidence && "
                f"cat /opt/research/{role}/.release-evidence",
            ]
        )
        fingerprint = env.get("RP_CONFIG_FINGERPRINT")
        fingerprint_matches = (
            fingerprint is None or f"RP_CONFIG_FINGERPRINT={fingerprint}\n" in value + "\n"
        )
        return (
            parse_release_env(value) == release and "RELEASE_ID=" in value and fingerprint_matches
        )
    except (subprocess.CalledProcessError, ValueError):
        return False


def doctor(
    role: str = typer.Argument("all", help="control | feed | notebook | all"),
) -> None:
    """Check provider configuration, host health, schema, logs, and release evidence."""
    env = load_env()
    cloud = detect_cloud(env)
    required = {
        "gcp": {
            "IMAGE",
            "RP_ENV",
            "RP_PROJECT_ID",
            "RP_REGION",
            "RP_STORAGE_URI",
            "RP_SCRATCH_URI",
        },
        "aws": {"IMAGE", "RP_ENV", "RP_REGION", "RP_STORAGE_URI", "RP_SCRATCH_URI"},
        "azure": {"IMAGE", "RP_ENV", "RP_RESOURCE_GROUP", "RP_STORAGE_URI", "RP_SCRATCH_URI"},
    }
    missing = sorted(key for key in required.get(cloud, set()) if not env.get(key))
    checks: list[dict[str, object]] = []
    if missing:
        checks.append({"check": "configuration", "passed": False, "missing": missing})
    else:
        checks.append({"check": "configuration", "passed": cloud in required})
    declarative = _local_configuration_status(env, refresh_terraform=True)
    checks.append(
        {
            "check": "configuration.sources-current",
            "passed": declarative is None or declarative.current,
            "reasons": list(declarative.reasons) if declarative else [],
        }
    )

    for name in _targets(role):
        state = _release_status(env, name)
        checks.append(
            {"check": f"{name}.health-and-digest", "passed": state.get("healthy") is True}
        )
        current = deployment._read_release_file(
            ssh_target(env, name), f"/opt/research/{name}/.env.tag"
        )
        checks.append(
            {
                "check": f"{name}.release-evidence",
                "passed": current is not None and _evidence_matches(env, name, current),
            }
        )
        try:
            deployment._verify_remote_logs(ssh_target(env, name), name, cloud)
            logs_ok = True
        except typer.Exit:
            logs_ok = False
        checks.append({"check": f"{name}.remote-logs", "passed": logs_ok})

        if name == "control":
            try:
                deployment._check_active_database_compatibility(
                    ssh_target(env, name), cloud, f"/opt/research/{name}"
                )
                schema_ok = current is not None
            except typer.Exit:
                schema_ok = False
            checks.append({"check": "control.schema-current", "passed": schema_ok})

    result = {
        "schema_version": 1,
        "environment": env.get("RP_ENV", ""),
        "provider": cloud,
        "healthy": all(item["passed"] is True for item in checks),
        "checks": checks,
    }
    typer.echo(json.dumps(result, indent=2, sort_keys=True))
    if not result["healthy"]:
        raise typer.Exit(1)


def rollback(
    role: str = typer.Argument("all", help="control | feed | notebook | all"),
    yes: bool = typer.Option(False, "--yes", help="Confirm the release mutation."),
) -> None:
    """Restore the previous compatible digest and health-gate the result."""
    if not yes:
        typer.secho("rollback requires --yes", fg=typer.colors.RED)
        raise typer.Exit(1)
    env = load_env()
    cloud = detect_cloud(env)
    if cloud not in {"gcp", "aws", "azure"}:
        typer.secho(f"rollback is unsupported for cloud {cloud!r}", fg=typer.colors.RED)
        raise typer.Exit(1)
    targets = _targets(role)
    originals: dict[str, Release] = {}
    previous_releases: dict[str, Release] = {}
    restored: list[tuple[str, str]] = []
    for name in targets:
        host = ssh_target(env, name)
        current = deployment._read_release_file(host, f"/opt/research/{name}/.env.tag")
        if current is None:
            typer.secho(f"{name} has no active release", fg=typer.colors.RED)
            raise typer.Exit(1)
        originals[name] = current
        previous = deployment._read_release_file(host, f"/opt/research/{name}/.env.previous-tag")
        if previous is None:
            typer.secho(f"{name} has no previous release", fg=typer.colors.RED)
            raise typer.Exit(1)
        previous_releases[name] = previous

    if len(set(previous_releases.values())) != 1:
        typer.secho(
            "roles do not share one previous release; roll them back individually",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    try:
        for name in targets:
            host = ssh_target(env, name)
            release = deployment._rollback_role(host, name, cloud, env)
            restored.append((name, host))
            eprint(f"{name} restored to {release.reference(env['IMAGE'])}")
        control_release = (
            deployment._read_release_file(
                ssh_target(env, "control"), "/opt/research/control/.env.tag"
            )
            if "control" in targets
            else None
        )
        if control_release is not None:
            deployment._update_batch_image(env, control_release)
            release_id = (
                f"{env.get('RP_ENV', 'unknown')}-rollback-{control_release.tag[:48]}-"
                f"{datetime.now(UTC):%Y%m%d%H%M%S}"
            )
            deployment._run_synthetic_probe(env, control_release, release_id)
        else:
            release_id = f"{env.get('RP_ENV', 'unknown')}-rollback-{datetime.now(UTC):%Y%m%d%H%M%S}"
        active = deployment._read_release_file(
            ssh_target(env, targets[0]), f"/opt/research/{targets[0]}/.env.tag"
        )
        if active is not None:
            deployment._record_release_evidence(env, targets, active, release_id)
    except (typer.Exit, RuntimeError, subprocess.CalledProcessError):
        typer.secho("rollback transaction failed; restoring original release", fg=typer.colors.RED)
        for name, host in reversed(restored):
            try:
                deployment._rollback_role(host, name, cloud, env)
            except (typer.Exit, RuntimeError, subprocess.CalledProcessError):
                typer.secho(f"could not restore original {name} release", fg=typer.colors.RED)
        if "control" in originals:
            try:
                deployment._update_batch_image(env, originals["control"])
            except (typer.Exit, RuntimeError, subprocess.CalledProcessError):
                typer.secho("could not restore original batch release", fg=typer.colors.RED)
        raise typer.Exit(1) from None

    eprint(f"rollback completed for {', '.join(targets)}", typer.colors.GREEN)
