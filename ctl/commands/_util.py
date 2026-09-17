"""Shared helpers: shelling out, reading .env, resolving the current tag."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import typer

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"
OPERATOR_ENV_KEYS = frozenset({"RP_CONFIG_FILE", "SSH_USER"})

# The deployment payload is an allowlist, not a blocklist. New local settings
# remain local until they are deliberately classified as safe to place on a
# production host. Secret values, SSH coordinates, and credential-file paths
# are never eligible; provider secret identifiers are non-secret references.
DEPLOYMENT_ENV_KEYS = frozenset(
    {
        "IMAGE",
        "AIRFLOW_HOME",
        "AIRFLOW_DB_HOST",
        "AIRFLOW_DB_PORT",
        "AIRFLOW_DB_USER",
        "AIRFLOW_DB_NAME",
        "AIRFLOW_REMOTE_LOGS",
        "AIRFLOW_LOG_CONN_ID",
        "AIRFLOW_SECRETS_BACKEND",
        "AIRFLOW_SECRETS_KWARGS",
        "RP_ENV",
        "RP_STORAGE_URI",
        "RP_SCRATCH_URI",
        "RP_CLOUD",
        "RP_PROJECT_ID",
        "RP_REGION",
        "RP_BATCH_JOB_NAME",
        "RP_BATCH_JOB_QUEUE",
        "RP_RESOURCE_GROUP",
        "RP_SUBSCRIPTION_ID",
        "RP_AZURE_ACI_SUBNET_ID",
        "RP_AZURE_JOB_IDENTITY_ID",
        "RP_AZURE_KEY_VAULT_URI",
        "RP_AZURE_MANAGED_IDENTITY_CLIENT_ID",
        "RP_VENDOR_CREDENTIAL_SECRET_ID",
        "RP_FEED_CREDENTIAL_SECRET_ID",
        "RP_FEED_WS_URL",
        "RP_FEED_SOURCE",
        "RP_FEED_DATASET",
        "RP_FEED_FLUSH_SECONDS",
        "RP_FEED_FLUSH_ROWS",
        "RP_ALERT_EMAILS",
        "RP_TIMEZONE",
        "RP_CONFIG_FINGERPRINT",
        "NOTEBOOKS_HOST_PATH",
    }
)

PROHIBITED_DEPLOYMENT_KEYS = frozenset(
    {
        "AIRFLOW_DB_PASSWORD",
        "AIRFLOW_FERNET_KEY",
        "AIRFLOW__CORE__FERNET_KEY",
        "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AZURE_CLIENT_SECRET",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "CLOUD_CREDS_PATH",
        "RP_VENDOR_CREDENTIAL",
        "RP_FEED_CREDENTIAL",
    }
)


def sh(command: list[str], *, cwd: Path | None = None, check: bool = True) -> int:
    """Run a command, echoing it first. Echoing is not decoration -- it is what
    makes a failed deploy reproducible by hand."""
    typer.secho("$ " + " ".join(shlex.quote(c) for c in command), fg=typer.colors.BRIGHT_BLACK)
    result = subprocess.run(command, cwd=cwd or REPO_ROOT)
    if check and result.returncode != 0:
        typer.secho(f"command failed with exit {result.returncode}", fg=typer.colors.RED)
        raise typer.Exit(result.returncode)
    return result.returncode


def capture(command: list[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(
        command, cwd=cwd or REPO_ROOT, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def load_local_env() -> dict[str, str]:
    """Parse the ignored operator env without loading generated configuration."""
    if not ENV_FILE.exists():
        typer.secho(f"missing {ENV_FILE}; copy .env.example first", fg=typer.colors.RED)
        raise typer.Exit(1)
    values: dict[str, str] = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_env() -> dict[str, str]:
    """Merge generated non-secret configuration with local operator settings.

    The generated file owns any key it contains. The ignored local file supplies
    only its path, SSH/operator coordinates, and credentials consumed by cloud
    CLIs. Conflicting duplication is rejected instead of silently choosing a
    precedence rule.
    """
    local = load_local_env()
    configured_path = local.get("RP_CONFIG_FILE")
    if not configured_path:
        return local

    from ctl.configuration import ConfigurationError, parse_env_file

    path = Path(configured_path)
    if not path.is_absolute():
        path = REPO_ROOT / path
    try:
        generated = parse_env_file(path)
    except ConfigurationError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None

    duplicates = sorted(generated.keys() & local.keys())
    if duplicates:
        typer.secho(
            "local .env duplicates generated configuration: " + ", ".join(duplicates),
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    unsupported = sorted(set(local) - OPERATOR_ENV_KEYS)
    if unsupported:
        typer.secho(
            "local .env contains settings not owned by the operator file: "
            + ", ".join(unsupported),
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    return {**generated, **local, "RP_CONFIG_FILE": str(path)}


def deployment_env(env: dict[str, str]) -> dict[str, str]:
    """Return only values approved for a host-side runtime configuration file."""
    prohibited = sorted(PROHIBITED_DEPLOYMENT_KEYS.intersection(env))
    if prohibited:
        typer.secho(
            "refusing secret-bearing deployment settings: " + ", ".join(prohibited),
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    selected = {key: env[key] for key in sorted(DEPLOYMENT_ENV_KEYS.intersection(env))}
    invalid = [key for key, value in selected.items() if "\n" in value or "\r" in value]
    if invalid:
        typer.secho(
            "deployment settings must be single-line values: " + ", ".join(invalid),
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    return selected


@contextmanager
def deployment_env_file(env: dict[str, str]) -> Iterator[Path]:
    """Write the allowlisted payload to a private temporary file for rsync."""
    values = deployment_env(env)
    path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            prefix="jarvis-runtime-",
            suffix=".env",
            encoding="utf-8",
            delete=False,
        ) as handle:
            path = Path(handle.name)
            for key, value in values.items():
                handle.write(f"{key}={value}\n")
        path.chmod(0o600)
        yield path
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


def git_sha(short: bool = True) -> str:
    args = ["git", "rev-parse"] + (["--short"] if short else []) + ["HEAD"]
    try:
        return capture(args)
    except subprocess.CalledProcessError:
        typer.secho("not a git repo; cannot derive an image tag", fg=typer.colors.RED)
        raise typer.Exit(1) from None


def require_clean_tree() -> None:
    """Refuse to tag an image with a SHA that does not describe the code in it."""
    if capture(["git", "status", "--porcelain"]):
        typer.secho(
            "working tree is dirty -- the SHA tag would not match the image contents.\n"
            "Commit, or pass --allow-dirty if you know what you are doing.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)


def resolve_tag(tag: str | None, allow_dirty: bool = False) -> str:
    if tag:
        return tag
    if not allow_dirty:
        require_clean_tree()
    return git_sha()


def detect_cloud(env: dict[str, str]) -> str:
    """Derive the provider from the storage URI.

    Same rule the runtime uses (``jobs.common.cloud.infer_cloud``), duplicated
    here so ``ctl`` stays importable without the app dependencies installed.
    """
    explicit = env.get("RP_CLOUD") or os.environ.get("RP_CLOUD")
    if explicit:
        return explicit
    uri = env.get("RP_STORAGE_URI", "") or os.environ.get("RP_STORAGE_URI", "")
    if uri.startswith("gs://"):
        return "gcp"
    if uri.startswith(("s3://", "s3a://")):
        return "aws"
    if uri.startswith(("abfs://", "abfss://", "az://", "wasbs://")):
        return "azure"
    return "local"


def registry_login(env: dict[str, str]) -> None:
    """Authenticate docker against the provider's registry."""
    cloud = detect_cloud(env)
    image = env["IMAGE"]
    host = image.split("/", 1)[0]
    if cloud == "gcp":
        sh(["gcloud", "auth", "configure-docker", host, "--quiet"])
    elif cloud == "aws":
        region = env["RP_REGION"]
        typer.secho("$ aws ecr get-login-password | docker login ...", fg=typer.colors.BRIGHT_BLACK)
        password = capture(["aws", "ecr", "get-login-password", "--region", region])
        subprocess.run(
            ["docker", "login", "--username", "AWS", "--password-stdin", host],
            input=password,
            text=True,
            check=True,
        )
    elif cloud == "azure":
        registry = host.split(".", 1)[0]
        sh(["az", "acr", "login", "--name", registry])


def ssh_target(env: dict[str, str], role: str) -> str:
    key = f"{role.upper()}_HOST"
    host = env.get(key) or os.environ.get(key)
    if not host:
        typer.secho(f"{key} is not set in .env", fg=typer.colors.RED)
        raise typer.Exit(1)
    user = env.get("SSH_USER") or os.environ.get("SSH_USER") or os.environ.get("USER", "")
    return f"{user}@{host}" if user else host


def eprint(message: str, colour: str = typer.colors.CYAN) -> None:
    typer.secho(message, fg=colour, err=False)
    sys.stdout.flush()
