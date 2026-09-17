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
