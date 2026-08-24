"""Build and push the one image."""

from __future__ import annotations

import typer

from ctl.commands._util import eprint, load_env, registry_login, resolve_tag, sh


def build(
    tag: str | None = typer.Option(None, help="Image tag. Defaults to the short git SHA."),
    allow_dirty: bool = typer.Option(False, help="Permit building from a dirty tree."),
    platform: str = typer.Option("linux/amd64", help="Target platform."),
    cloud: str | None = typer.Option(
        None, help="Provider stack to bake in. Defaults to the .env cloud."
    ),
) -> None:
    """Build the image and tag it with the git SHA."""
    from ctl.commands._util import detect_cloud

    env = load_env()
    image = env["IMAGE"]
    resolved = resolve_tag(tag, allow_dirty)
    target_cloud = cloud or detect_cloud(env)

    sh(
        [
            "docker",
            "build",
            "--platform",
            platform,
            "--build-arg",
            f"CLOUD={target_cloud}",
            "-f",
            "docker/Dockerfile",
            "-t",
            f"{image}:{resolved}",
            "--cache-from",
            f"{image}:latest",
            "--build-arg",
            "BUILDKIT_INLINE_CACHE=1",
            ".",
        ]
    )
    eprint(f"built {image}:{resolved} ({target_cloud} stack)")


def push(
    tag: str | None = typer.Option(None, help="Image tag. Defaults to the short git SHA."),
    allow_dirty: bool = typer.Option(False, help="Permit pushing from a dirty tree."),
    also_latest: bool = typer.Option(True, help="Also move the :latest tag."),
) -> None:
    """Push the image to the registry."""
    env = load_env()
    image = env["IMAGE"]
    resolved = resolve_tag(tag, allow_dirty)

    registry_login(env)
    sh(["docker", "push", f"{image}:{resolved}"])
    if also_latest:
        # :latest is a build cache source only. Nothing ever *deploys* it.
        sh(["docker", "tag", f"{image}:{resolved}", f"{image}:latest"])
        sh(["docker", "push", f"{image}:latest"])
    eprint(f"pushed {image}:{resolved}")
