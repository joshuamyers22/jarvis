"""Immutable release references shared by deployment commands.

A human-friendly tag identifies the source revision.  A registry digest is the
deployment identity: tags may move, while a digest cannot.  Both values travel
together so status output remains understandable without weakening pinning.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass

import typer

from ctl.commands._util import capture, registry_login

TAG_PATTERN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}")
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


@dataclass(frozen=True)
class Release:
    """One immutable application release."""

    tag: str
    digest: str

    def __post_init__(self) -> None:
        if not TAG_PATTERN.fullmatch(self.tag):
            raise ValueError(f"invalid image tag: {self.tag!r}")
        if not DIGEST_PATTERN.fullmatch(self.digest):
            raise ValueError(f"invalid image digest: {self.digest!r}")

    def reference(self, image: str) -> str:
        return f"{image}:{self.tag}@{self.digest}"

    def env_text(self) -> str:
        return (
            f"IMAGE_TAG={self.tag}\n"
            f"IMAGE_DIGEST={self.digest}\n"
            f"IMAGE_DIGEST_SUFFIX=@{self.digest}\n"
        )


def parse_release_env(value: str) -> Release:
    """Parse the two-key, non-secret release file used on hosts."""
    fields: dict[str, str] = {}
    for line in value.splitlines():
        key, separator, item = line.partition("=")
        if separator and key in {"IMAGE_TAG", "IMAGE_DIGEST"}:
            fields[key] = item
    try:
        return Release(fields["IMAGE_TAG"], fields["IMAGE_DIGEST"])
    except (KeyError, ValueError) as exc:
        raise ValueError("release file must contain a valid IMAGE_TAG and IMAGE_DIGEST") from exc


def resolve_digest(env: dict[str, str], tag: str) -> Release:
    """Resolve a registry tag once and return its immutable manifest digest."""
    if not TAG_PATTERN.fullmatch(tag):
        typer.secho(f"invalid image tag: {tag!r}", fg=typer.colors.RED)
        raise typer.Exit(1)

    registry_login(env)
    image = env["IMAGE"]
    try:
        raw = capture(
            [
                "docker",
                "buildx",
                "imagetools",
                "inspect",
                f"{image}:{tag}",
                "--format",
                "{{json .Manifest.Digest}}",
            ]
        )
        digest = json.loads(raw)
        return Release(tag, digest)
    except (json.JSONDecodeError, subprocess.CalledProcessError, TypeError, ValueError) as exc:
        typer.secho(
            f"registry returned no valid sha256 digest for {image}:{tag}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1) from exc
