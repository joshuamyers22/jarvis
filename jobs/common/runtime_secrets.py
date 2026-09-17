"""Resolve workload credentials through attached cloud identity at process start.

Deployment configuration carries only secret identifiers. Values live solely in
the child process environment and are never printed or written to disk.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable, Mapping, Sequence

from jobs.common.cloud import fetch_secret, infer_cloud

ROLE_BINDINGS = {
    "feed": ("RP_FEED_CREDENTIAL_SECRET_ID", "RP_FEED_CREDENTIAL"),
    "job": ("RP_VENDOR_CREDENTIAL_SECRET_ID", "RP_VENDOR_CREDENTIAL"),
}


def resolved_environment(
    role: str,
    env: Mapping[str, str],
    *,
    fetcher: Callable[[str, str, Mapping[str, str]], str] = fetch_secret,
) -> dict[str, str]:
    """Return a child environment with the role's credential materialized."""
    try:
        reference_key, value_key = ROLE_BINDINGS[role]
    except KeyError:
        raise RuntimeError(f"unsupported runtime role: {role}") from None

    child = dict(env)
    reference = env.get(reference_key, "")
    if not reference:
        if env.get("RP_ENV") == "prod":
            raise RuntimeError(f"{reference_key} is required in production")
        return child

    cloud = env.get("RP_CLOUD") or infer_cloud(env.get("RP_STORAGE_URI", "")).value
    child[value_key] = fetcher(cloud, reference, env)
    return child


def credential_headers(name: str, env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Parse the deliberately narrow JSON credential contract.

    Secret values are JSON objects of the form ``{"headers": {"Name": "value"}}``.
    Keeping the contract to HTTP headers avoids arbitrary environment injection.
    """
    value = (env or os.environ).get(name)
    if not value:
        return {}
    try:
        payload = json.loads(value)
        headers = payload["headers"]
    except (json.JSONDecodeError, KeyError, TypeError):
        raise RuntimeError(f"{name} must be JSON containing a headers object") from None
    if not isinstance(headers, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in headers.items()
    ):
        raise RuntimeError(f"{name}.headers must contain only string keys and values")
    return headers


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)
    execute = subparsers.add_parser("exec")
    execute.add_argument("--role", choices=sorted(ROLE_BINDINGS), required=True)
    execute.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if not args.command or args.command[0] != "--" or len(args.command) == 1:
        parser.error("exec requires -- followed by a command")

    command = args.command[1:]
    child_env = resolved_environment(args.role, os.environ)
    os.execvpe(command[0], command, child_env)


if __name__ == "__main__":
    main()
