from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.gcp_recovery_drill import (
    DrillConfig,
    DrillError,
    RecoveryDrill,
    generation_from_uri,
    plan,
    safe_drill_id,
)

DRILL_ID = "20260917t120000z-abcdef12"


def config(tmp_path: Path, **overrides) -> DrillConfig:
    values = {
        "project": "jarvis-research-stage",
        "region": "us-central1",
        "zone": "us-central1-a",
        "data_bucket": "jarvis-research-stage-data",
        "backup_bucket": "jarvis-research-stage-backup",
        "state_bucket": "jarvis-terraform-state",
        "state_prefix": "environments/stage",
        "image": (
            "us-central1-docker.pkg.dev/jarvis/research/base:"
            "0123456789abcdef0123456789abcdef01234567"
        ),
        "operator": "github:operator",
        "ticket": "RECOVERY-123",
        "evidence_dir": tmp_path,
    }
    values.update(overrides)
    return DrillConfig(**values)


@pytest.mark.parametrize(
    ("project", "message"),
    [
        ("jarvis-research-prod", "only in -dev or -stage"),
        ("jarvis-research", "only in -dev or -stage"),
    ],
)
def test_production_and_unsuffixed_projects_are_rejected(
    tmp_path: Path, project: str, message: str
) -> None:
    with pytest.raises(DrillError, match=message):
        config(tmp_path, project=project).validate()


def test_state_and_storage_boundaries_must_match_environment(tmp_path: Path) -> None:
    with pytest.raises(DrillError, match="state prefix"):
        config(tmp_path, state_prefix="environments/prod").validate()
    with pytest.raises(DrillError, match="data bucket"):
        config(tmp_path, data_bucket="jarvis-research-prod-data").validate()


def test_plan_names_only_isolated_restore_targets(tmp_path: Path) -> None:
    result = plan(config(tmp_path), DRILL_ID)

    assert result["environment"] == "stage"
    assert result["production_resources"] == "forbidden"
    assert all("prod" not in mutation for mutation in result["mutations"])
    assert any("recovery-drills" in mutation for mutation in result["mutations"])
    assert any("replacement host" in mutation for mutation in result["mutations"])


def test_generation_parser_requires_the_exact_object() -> None:
    uri = "gs://state/environments/stage/default.tfstate"
    assert generation_from_uri(f"{uri}#123456", uri) == "123456"
    with pytest.raises(DrillError, match="unexpected object URI"):
        generation_from_uri("gs://state/environments/prod/default.tfstate#123456", uri)


def test_drill_id_rejects_unsafe_or_production_names() -> None:
    assert safe_drill_id(DRILL_ID) == DRILL_ID
    for value in ("short", "UPPERCASE-NAME", "20260917-prod-drill"):
        with pytest.raises(DrillError):
            safe_drill_id(value)


def test_long_drill_ids_keep_resource_suffixes_distinct(tmp_path: Path) -> None:
    drill = RecoveryDrill(config(tmp_path), "a" * 49, FailedPreflightRunner())

    names = {
        drill._resource_name("notebook"),
        drill._resource_name("notebook-restore"),
        drill._resource_name("notebook-host"),
    }
    assert len(names) == 3
    assert all(len(name) <= 62 for name in names)


class FailedPreflightRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, command: list[str]) -> str:
        self.commands.append(command)
        return json.dumps({"projectId": "different-stage"})


def test_failed_preflight_skips_every_cloud_mutation(tmp_path: Path) -> None:
    runner = FailedPreflightRunner()
    drill = RecoveryDrill(config(tmp_path), DRILL_ID, runner)

    evidence, evidence_path = drill.run()

    assert evidence["status"] == "failed"
    assert evidence["exercises"]["preflight"]["status"] == "failed"
    assert all(
        exercise["status"] == "skipped"
        for name, exercise in evidence["exercises"].items()
        if name != "preflight"
    )
    assert len(runner.commands) == 1
    assert evidence_path.exists()
    assert "evidence_uri" not in evidence


class NotebookRestoreRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, command: list[str]) -> str:
        self.commands.append(command)
        joined = " ".join(command)
        if "disks describe research-stage-notebooks" in joined:
            return json.dumps(
                {
                    "sizeGb": "200",
                    "resourcePolicies": [
                        "projects/jarvis-research-stage/regions/us-central1/"
                        "resourcePolicies/research-stage-notebook-daily"
                    ],
                }
            )
        if "disks describe recovery-drill-" in joined:
            return json.dumps(
                {
                    "status": "READY",
                    "sizeGb": "200",
                    "sourceSnapshot": (
                        f"projects/test/global/snapshots/recovery-drill-{DRILL_ID}-notebook"
                    ),
                }
            )
        if "instances describe research-stage-notebook" in joined:
            return json.dumps(
                {
                    "metadata": {
                        "items": [
                            {
                                "key": "jarvis-host-image",
                                "value": "projects/test/global/images/jarvis-host-image",
                            }
                        ]
                    },
                    "networkInterfaces": [
                        {
                            "network": "projects/test/global/networks/private",
                            "subnetwork": "projects/test/regions/us-central1/subnetworks/workloads",
                        }
                    ],
                }
            )
        if "compute ssh" in joined:
            return json.dumps(
                {
                    "schema_version": 1,
                    "mode": "gcp-pd",
                    "filesystem_uuid": "1234-abcd",
                    "mount_path": "/mnt/jarvis-notebooks",
                    "verified": True,
                }
            )
        return ""


def test_notebook_restore_is_mounted_on_isolated_replacement_host(tmp_path: Path) -> None:
    runner = NotebookRestoreRunner()
    drill = RecoveryDrill(config(tmp_path), DRILL_ID, runner)

    result = drill.notebook_volume()

    assert result["status"] == "passed"
    assert result["source_disk"] == "research-stage-notebooks"
    assert result["mount_verified"] is True
    assert result["filesystem_uuid"] == "1234-abcd"
    create = next(
        command for command in runner.commands if "instances" in command and "create" in command
    )
    assert "--no-service-account" in create
    assert "--no-scopes" in create
    assert any("device-name=jarvis-notebooks" in item for item in create)
    cleanup = [" ".join(command) for command in runner.commands[-3:]]
    assert "instances delete" in cleanup[0]
    assert "disks delete" in cleanup[1]
    assert "snapshots delete" in cleanup[2]
