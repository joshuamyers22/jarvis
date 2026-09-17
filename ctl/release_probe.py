"""Release-level synthetic check executed by the deployed batch definition."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import UTC, datetime

from jobs.common import storage

RESULT_PREFIX = "JARVIS_RELEASE_PROBE="
RELEASE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


def run_probe(release_id: str, expected_cloud: str) -> dict[str, str]:
    if not RELEASE_ID_PATTERN.fullmatch(release_id):
        raise ValueError("release id must contain only letters, numbers, dot, dash, or underscore")

    runtime_cloud = os.environ.get("RP_CLOUD", "")
    image_cloud = os.environ.get("RP_IMAGE_CLOUD", "")
    if runtime_cloud != expected_cloud or image_cloud != expected_cloud:
        raise RuntimeError(
            "provider mismatch: "
            f"expected={expected_cloud} runtime={runtime_cloud} image={image_cloud}"
        )

    scratch = os.environ.get("RP_SCRATCH_URI", "").rstrip("/")
    if not scratch:
        raise RuntimeError("RP_SCRATCH_URI is required")
    prefix = f"{scratch}/release-probes/{release_id}"
    payload = {
        "release_id": release_id,
        "cloud": expected_cloud,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    storage.write_json(f"{prefix}/probe.json", payload)
    storage.mark_success(prefix, payload)
    if storage.read_json(f"{prefix}/probe.json") != payload or not storage.is_complete(prefix):
        raise RuntimeError("synthetic output could not be read back")
    return {"release_id": release_id, "cloud": expected_cloud, "output_prefix": prefix}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--expected-cloud", required=True, choices=("gcp", "aws", "azure"))
    args = parser.parse_args(argv)
    result = run_probe(args.release_id, args.expected_cloud)
    print(RESULT_PREFIX + json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
