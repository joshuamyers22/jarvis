from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

SUPERVISOR = Path("packer/gcp/files/jarvis-compose")


def test_health_failure_is_machine_readable(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(SUPERVISOR), "health", "control"],
        check=False,
        capture_output=True,
        env={**os.environ, "JARVIS_ROOT": str(tmp_path)},
        text=True,
    )

    assert result.returncode == 1
    assert json.loads(result.stdout) == {
        "schema_version": 1,
        "role": "control",
        "healthy": False,
        "error": "configuration-invalid",
        "services": [],
    }


def test_unknown_role_is_rejected_before_host_access(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(SUPERVISOR), "health", "unknown"],
        check=False,
        capture_output=True,
        env={**os.environ, "JARVIS_ROOT": str(tmp_path)},
        text=True,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "unsupported Jarvis role" in result.stderr
