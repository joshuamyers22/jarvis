"""Shared helpers: shelling out, reading .env, resolving the current tag."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

import typer

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"


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


def load_env() -> dict[str, str]:
    """Parse .env. Deliberately not python-dotenv -- one fewer dependency and
    the format we accept is exactly the format docker compose accepts."""
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
