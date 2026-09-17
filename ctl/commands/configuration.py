"""Render and validate declarative runtime configuration."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from ctl.commands._util import REPO_ROOT, load_local_env
from ctl.configuration import (
    ConfigurationError,
    configuration_status,
    render_configuration,
    terraform_output,
    write_configuration,
)

app = typer.Typer(
    name="config",
    help="Render and verify non-secret runtime configuration.",
    no_args_is_help=True,
)


def _path(value: Path) -> Path:
    return value if value.is_absolute() else REPO_ROOT / value


@app.command("render")
def render(
    environment: str = typer.Option(..., "--environment", "-e", help="dev | stage | prod"),
    group: str = typer.Option("default", help="Group overlay name under config/runtime/groups."),
    terraform_dir: Path | None = typer.Option(  # noqa: B008
        None,
        help="Applied Terraform root; defaults to terraform/live/gcp/ENVIRONMENT.",
    ),
    terraform_env_file: Path | None = typer.Option(  # noqa: B008
        None,
        help="Ignored credential/input env file; defaults to TERRAFORM_DIR/.env.live when present.",
    ),
    overlay: list[Path] | None = typer.Option(  # noqa: B008
        None,
        "--overlay",
        help="Additional TOML overlay, repeatable and applied last.",
    ),
    output: Path | None = typer.Option(  # noqa: B008
        None,
        help="Generated env path; defaults to .runtime/ENVIRONMENT-GROUP.env.",
    ),
) -> None:
    """Render Terraform state and versioned overlays into a deterministic env file."""
    root = _path(terraform_dir or Path(f"terraform/live/gcp/{environment}"))
    env_path: Path | None = _path(terraform_env_file) if terraform_env_file else root / ".env.live"
    if terraform_env_file is None and env_path is not None and not env_path.exists():
        env_path = None
    output_path = _path(output or Path(f".runtime/{environment}-{group}.env"))
    overlays = [_path(path) for path in (overlay or [])]
    try:
        raw_outputs = terraform_output(root, env_path)
        rendered = render_configuration(
            raw_outputs,
            environment=environment,
            group=group,
            overlays=overlays,
            terraform_dir=root,
            terraform_env_file=env_path,
        )
        manifest = write_configuration(rendered, output_path)
    except ConfigurationError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None
    typer.echo(
        json.dumps(
            {
                "configuration": str(output_path),
                "manifest": str(manifest),
                "fingerprint": rendered.fingerprint,
                "terraform_fingerprint": rendered.terraform_fingerprint,
            },
            indent=2,
            sort_keys=True,
        )
    )


@app.command("check")
def check(
    file: Path | None = typer.Option(  # noqa: B008
        None,
        "--file",
        help="Generated env file; defaults to RP_CONFIG_FILE from .env.",
    ),
    refresh_terraform: bool = typer.Option(
        True,
        "--refresh-terraform/--no-refresh-terraform",
        help="Compare against current Terraform outputs as well as local overlays.",
    ),
) -> None:
    """Fail when the rendered file, overlays, or Terraform outputs have drifted."""
    local = load_local_env()
    selected = file or (Path(local["RP_CONFIG_FILE"]) if local.get("RP_CONFIG_FILE") else None)
    if selected is None:
        typer.secho("RP_CONFIG_FILE is not set and --file was not provided", fg=typer.colors.RED)
        raise typer.Exit(1)
    status = configuration_status(_path(selected), refresh_terraform=refresh_terraform)
    typer.echo(json.dumps(status.as_dict(), indent=2, sort_keys=True))
    if not status.current:
        raise typer.Exit(1)


@app.command("show")
def show(
    file: Path | None = typer.Option(  # noqa: B008
        None,
        "--file",
        help="Generated env file; defaults to RP_CONFIG_FILE from .env.",
    ),
) -> None:
    """Print configuration identity and source metadata without secret material."""
    local = load_local_env()
    selected = file or (Path(local["RP_CONFIG_FILE"]) if local.get("RP_CONFIG_FILE") else None)
    if selected is None:
        typer.secho("RP_CONFIG_FILE is not set and --file was not provided", fg=typer.colors.RED)
        raise typer.Exit(1)
    config_path = _path(selected)
    status = configuration_status(config_path, refresh_terraform=False)
    result = status.as_dict()
    if status.manifest:
        result.update(
            {
                "environment": status.manifest.get("environment"),
                "group": status.manifest.get("group"),
                "sources": status.manifest.get("sources"),
                "terraform_dir": status.manifest.get("terraform_dir"),
            }
        )
    typer.echo(json.dumps(result, indent=2, sort_keys=True))
    if not status.current:
        raise typer.Exit(1)
