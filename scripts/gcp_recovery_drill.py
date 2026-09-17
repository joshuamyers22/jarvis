"""Quarterly GCP recovery drill with fail-closed production safeguards.

The drill never overwrites a managed database, state object, or notebook disk.
Every restore targets a uniquely named temporary resource and cleanup is part of
the recorded evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

RPO_SECONDS = 300
RTO_SECONDS = 7200
RESULT_MARKER = "JARVIS_RECOVERY_RESULT="
PROJECT_PATTERN = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
SAFE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{7,48}$")


class DrillError(RuntimeError):
    """A safe, operator-facing drill failure without command output."""


@dataclass(frozen=True)
class DrillConfig:
    project: str
    region: str
    zone: str
    data_bucket: str
    backup_bucket: str
    state_bucket: str
    state_prefix: str
    image: str
    operator: str
    ticket: str
    evidence_dir: Path

    @property
    def environment(self) -> str:
        return self.project.rsplit("-", 1)[-1]

    @property
    def source_sql_instance(self) -> str:
        return f"research-{self.environment}-airflow"

    @property
    def control_instance(self) -> str:
        return f"research-{self.environment}-control"

    @property
    def notebook_instance(self) -> str:
        return f"research-{self.environment}-notebook"

    @property
    def notebook_snapshot_policy(self) -> str:
        return f"research-{self.environment}-notebook-daily"

    @property
    def state_uri(self) -> str:
        return f"gs://{self.state_bucket}/{self.state_prefix}/default.tfstate"

    def validate(self) -> None:
        if not PROJECT_PATTERN.fullmatch(self.project):
            raise DrillError("project must be a valid GCP project ID")
        if self.environment not in {"dev", "stage"}:
            raise DrillError("recovery drills are allowed only in -dev or -stage projects")
        if self.state_prefix != f"environments/{self.environment}":
            raise DrillError("state prefix must match the selected non-production environment")
        if len({self.data_bucket, self.backup_bucket, self.state_bucket}) != 3:
            raise DrillError("data, backup, and state buckets must be distinct")
        env_token = re.compile(rf"(^|[-_.]){self.environment}($|[-_.])")
        for label, bucket in (
            ("data", self.data_bucket),
            ("backup", self.backup_bucket),
        ):
            if not env_token.search(bucket):
                raise DrillError(f"{label} bucket must identify the {self.environment} environment")
        image_tag = self.image.rsplit(":", 1)[-1]
        if any(char.isspace() for char in self.image) or not re.fullmatch(
            r"[0-9a-f]{40}", image_tag
        ):
            raise DrillError("image must be pinned to a full 40-character Git SHA")
        if not self.operator.strip() or not self.ticket.strip():
            raise DrillError("operator and ticket are required for recovery evidence")


class CommandRunner:
    def run(self, command: list[str]) -> str:
        print("$ " + shlex.join(command), flush=True)
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise DrillError(f"command failed with exit {result.returncode}: {shlex.join(command)}")
        return result.stdout.strip()


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_time(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def new_drill_id(now: datetime | None = None) -> str:
    timestamp = (now or utc_now()).strftime("%Y%m%dt%H%M%Sz").lower()
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def safe_drill_id(value: str) -> str:
    if not SAFE_ID_PATTERN.fullmatch(value) or "prod" in value:
        raise DrillError("drill ID must be 8-49 lowercase letters, digits, or hyphens")
    return value


def parse_json(value: str, description: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        raise DrillError(f"{description} did not return valid JSON") from None
    if not isinstance(parsed, dict):
        raise DrillError(f"{description} must return a JSON object")
    return parsed


def generation_from_uri(value: str, expected_uri: str) -> str:
    prefix = f"{expected_uri}#"
    if not value.startswith(prefix) or not value[len(prefix) :].isdigit():
        raise DrillError("version listing returned an unexpected object URI")
    return value[len(prefix) :]


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class RecoveryDrill:
    def __init__(self, config: DrillConfig, drill_id: str, runner: CommandRunner) -> None:
        config.validate()
        self.config = config
        self.drill_id = safe_drill_id(drill_id)
        self.runner = runner
        self.prefix = f"recovery-drill-{drill_id}"[:62].rstrip("-")
        self.cleanup: dict[str, dict[str, str]] = {}

    def _gcloud(self, *args: str) -> list[str]:
        return ["gcloud", *args]

    def _cleanup_commands(self, name: str, commands: list[list[str]]) -> None:
        if not commands:
            self.cleanup[name] = {"status": "not-required"}
            return
        failures = 0
        for command in commands:
            try:
                self.runner.run(command)
            except Exception:
                failures += 1
        if failures:
            self.cleanup[name] = {"status": "failed", "failed_commands": str(failures)}
            raise DrillError(f"{name} cleanup failed for {failures} resource(s)")
        self.cleanup[name] = {"status": "passed"}

    def preflight(self) -> dict[str, Any]:
        project = parse_json(
            self.runner.run(
                self._gcloud("projects", "describe", self.config.project, "--format=json")
            ),
            "project describe",
        )
        if project.get("projectId") != self.config.project:
            raise DrillError("authenticated project did not match the requested project")

        control_status = self.runner.run(
            self._gcloud(
                "compute",
                "instances",
                "describe",
                self.config.control_instance,
                "--project",
                self.config.project,
                "--zone",
                self.config.zone,
                "--format=value(status)",
            )
        )
        if control_status != "RUNNING":
            raise DrillError("control instance must be RUNNING for private database validation")

        notebook_status = self.runner.run(
            self._gcloud(
                "compute",
                "instances",
                "describe",
                self.config.notebook_instance,
                "--project",
                self.config.project,
                "--zone",
                self.config.zone,
                "--format=value(status)",
            )
        )
        if notebook_status != "TERMINATED":
            raise DrillError("notebook must be TERMINATED for a consistent volume drill")
        source_sql = parse_json(
            self.runner.run(
                self._gcloud(
                    "sql",
                    "instances",
                    "describe",
                    self.config.source_sql_instance,
                    "--project",
                    self.config.project,
                    "--format=json",
                )
            ),
            "source Cloud SQL instance",
        )
        backup = source_sql.get("settings", {}).get("backupConfiguration", {})
        if source_sql.get("state") != "RUNNABLE" or not backup.get("pointInTimeRecoveryEnabled"):
            raise DrillError("source Cloud SQL must be RUNNABLE with PITR enabled")
        return {
            "project": self.config.project,
            "control_status": control_status,
            "notebook_status": notebook_status,
            "source_sql_status": source_sql["state"],
            "pitr_enabled": True,
        }

    def cloud_sql(self) -> dict[str, Any]:
        started = utc_now()
        restore_point = started - timedelta(seconds=RPO_SECONDS)
        target = f"{self.prefix}-sql"[:98].rstrip("-")
        created = False
        try:
            self.runner.run(
                self._gcloud(
                    "sql",
                    "instances",
                    "clone",
                    self.config.source_sql_instance,
                    target,
                    "--point-in-time",
                    iso_time(restore_point),
                    "--project",
                    self.config.project,
                    "--quiet",
                )
            )
            created = True
            instance = parse_json(
                self.runner.run(
                    self._gcloud(
                        "sql",
                        "instances",
                        "describe",
                        target,
                        "--project",
                        self.config.project,
                        "--format=json",
                    )
                ),
                "restored Cloud SQL instance",
            )
            if instance.get("state") != "RUNNABLE":
                raise DrillError("restored Cloud SQL instance is not RUNNABLE")
            private_ips = [
                item.get("ipAddress")
                for item in instance.get("ipAddresses", [])
                if item.get("type") == "PRIVATE"
            ]
            if len(private_ips) != 1 or not private_ips[0]:
                raise DrillError("restored Cloud SQL instance lacks one private IP")

            remote_command = shlex.join(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "host",
                    "-e",
                    f"RP_PROJECT_ID={self.config.project}",
                    "-e",
                    "RP_CLOUD=gcp",
                    self.config.image,
                    "python",
                    "-m",
                    "jobs.recovery_validate",
                    "database",
                    "--target-host",
                    private_ips[0],
                ]
            )
            validation_output = self.runner.run(
                self._gcloud(
                    "compute",
                    "ssh",
                    self.config.control_instance,
                    "--project",
                    self.config.project,
                    "--zone",
                    self.config.zone,
                    "--tunnel-through-iap",
                    "--quiet",
                    "--command",
                    remote_command,
                )
            )
            marker_lines = [
                line for line in validation_output.splitlines() if line.startswith(RESULT_MARKER)
            ]
            if len(marker_lines) != 1:
                raise DrillError("database validator did not return one evidence record")
            validation = parse_json(marker_lines[0][len(RESULT_MARKER) :], "database validation")
            elapsed = int((utc_now() - started).total_seconds())
            if elapsed > RTO_SECONDS:
                raise DrillError("Cloud SQL restore exceeded the two-hour RTO")
            return {
                "status": "passed",
                "source_instance": self.config.source_sql_instance,
                "target_instance": target,
                "requested_restore_time": iso_time(restore_point),
                "rpo_seconds": RPO_SECONDS,
                "rto_seconds": elapsed,
                "instance_state": instance["state"],
                "database_version": instance.get("databaseVersion"),
                "validation": validation,
            }
        finally:
            commands = []
            if created:
                commands.extend(
                    [
                        self._gcloud(
                            "sql",
                            "instances",
                            "patch",
                            target,
                            "--no-deletion-protection",
                            "--project",
                            self.config.project,
                            "--quiet",
                        ),
                        self._gcloud(
                            "sql",
                            "instances",
                            "delete",
                            target,
                            "--project",
                            self.config.project,
                            "--quiet",
                        ),
                    ]
                )
            self._cleanup_commands("cloud_sql", commands)

    def object_version(self) -> dict[str, Any]:
        uri = f"gs://{self.config.data_bucket}/recovery-drills/{self.drill_id}/object.txt"
        generations: list[str] = []
        first = f"jarvis-recovery-v1-{self.drill_id}".encode()
        second = f"jarvis-recovery-v2-{self.drill_id}".encode()
        with tempfile.TemporaryDirectory(prefix="jarvis-recovery-") as directory:
            first_path = Path(directory) / "v1.txt"
            second_path = Path(directory) / "v2.txt"
            first_path.write_bytes(first)
            second_path.write_bytes(second)
            try:
                self.runner.run(self._gcloud("storage", "cp", str(first_path), uri))
                generations.append(self._object_generation(uri))
                time.sleep(1.1)  # Cloud Storage limits rapid replacement of one object.
                self.runner.run(self._gcloud("storage", "cp", str(second_path), uri))
                current = self._object_generation(uri)
                generations.append(current)
                time.sleep(1.1)
                self.runner.run(
                    self._gcloud(
                        "storage",
                        "cp",
                        f"{uri}#{generations[0]}",
                        uri,
                        f"--if-generation-match={current}",
                    )
                )
                generations.append(self._object_generation(uri))
                recovered = self.runner.run(self._gcloud("storage", "cat", uri)).encode()
                if recovered != first:
                    raise DrillError("restored object content did not match its original checksum")
                return {
                    "status": "passed",
                    "uri": uri,
                    "source_generation": generations[0],
                    "overwritten_generation": generations[1],
                    "restored_generation": generations[2],
                    "expected_sha256": sha256(first),
                    "restored_sha256": sha256(recovered),
                }
            finally:
                self._cleanup_commands(
                    "object_version",
                    [
                        self._gcloud("storage", "rm", f"{uri}#{generation}")
                        for generation in reversed(generations)
                    ],
                )

    def _object_generation(self, uri: str) -> str:
        generation = self.runner.run(
            self._gcloud("storage", "objects", "describe", uri, "--format=value(generation)")
        )
        if not generation.isdigit():
            raise DrillError("Cloud Storage returned an invalid generation")
        return generation

    def terraform_state(self) -> dict[str, Any]:
        versions = self.runner.run(
            self._gcloud("storage", "ls", "--all-versions", self.config.state_uri)
        ).splitlines()
        generations = [generation_from_uri(line, self.config.state_uri) for line in versions]
        current = self._object_generation(self.config.state_uri)
        previous = [item for item in generations if item != current]
        if not previous:
            raise DrillError("Terraform state has no noncurrent generation to recover")
        source_generation = max(previous, key=int)
        restored_uri = (
            f"gs://{self.config.state_bucket}/recovery-drills/{self.drill_id}/default.tfstate"
        )
        restored_generation: str | None = None
        try:
            self.runner.run(
                self._gcloud(
                    "storage",
                    "cp",
                    f"{self.config.state_uri}#{source_generation}",
                    restored_uri,
                    "--if-generation-match=0",
                )
            )
            restored_generation = self._object_generation(restored_uri)
            state = parse_json(
                self.runner.run(self._gcloud("storage", "cat", restored_uri)),
                "recovered Terraform state",
            )
            required = {"version", "terraform_version", "serial", "lineage", "resources"}
            if not required.issubset(state) or not isinstance(state["resources"], list):
                raise DrillError("recovered Terraform state failed structural validation")
            return {
                "status": "passed",
                "source_uri": self.config.state_uri,
                "source_generation": source_generation,
                "isolated_restore_uri": restored_uri,
                "state_version": state["version"],
                "terraform_version": state["terraform_version"],
                "serial": state["serial"],
                "resource_count": len(state["resources"]),
            }
        finally:
            commands = []
            if restored_generation is not None:
                commands.append(
                    self._gcloud("storage", "rm", f"{restored_uri}#{restored_generation}")
                )
            self._cleanup_commands("terraform_state", commands)

    def notebook_volume(self) -> dict[str, Any]:
        snapshot = f"{self.prefix}-notebook"[:62].rstrip("-")
        disk = f"{self.prefix}-notebook-restore"[:62].rstrip("-")
        snapshot_created = False
        disk_created = False
        try:
            source = parse_json(
                self.runner.run(
                    self._gcloud(
                        "compute",
                        "disks",
                        "describe",
                        self.config.notebook_instance,
                        "--project",
                        self.config.project,
                        "--zone",
                        self.config.zone,
                        "--format=json",
                    )
                ),
                "notebook source disk",
            )
            policies = source.get("resourcePolicies", [])
            if not any(
                item.endswith(f"/{self.config.notebook_snapshot_policy}") for item in policies
            ):
                raise DrillError("notebook disk lacks the managed snapshot schedule")
            self.runner.run(
                self._gcloud(
                    "compute",
                    "snapshots",
                    "create",
                    snapshot,
                    "--source-disk",
                    self.config.notebook_instance,
                    "--source-disk-zone",
                    self.config.zone,
                    "--storage-location",
                    self.config.region,
                    "--project",
                    self.config.project,
                    "--quiet",
                )
            )
            snapshot_created = True
            self.runner.run(
                self._gcloud(
                    "compute",
                    "disks",
                    "create",
                    disk,
                    "--source-snapshot",
                    snapshot,
                    "--zone",
                    self.config.zone,
                    "--project",
                    self.config.project,
                    "--quiet",
                )
            )
            disk_created = True
            restored = parse_json(
                self.runner.run(
                    self._gcloud(
                        "compute",
                        "disks",
                        "describe",
                        disk,
                        "--project",
                        self.config.project,
                        "--zone",
                        self.config.zone,
                        "--format=json",
                    )
                ),
                "restored notebook disk",
            )
            if restored.get("status") != "READY" or not str(
                restored.get("sourceSnapshot", "")
            ).endswith(f"/{snapshot}"):
                raise DrillError("restored notebook disk is not READY from the expected snapshot")
            if int(restored.get("sizeGb", 0)) < int(source.get("sizeGb", 0)):
                raise DrillError("restored notebook disk is smaller than its source")
            return {
                "status": "passed",
                "source_disk": self.config.notebook_instance,
                "snapshot": snapshot,
                "restored_disk": disk,
                "source_size_gb": int(source["sizeGb"]),
                "restored_size_gb": int(restored["sizeGb"]),
                "snapshot_policy": self.config.notebook_snapshot_policy,
            }
        finally:
            commands = []
            if disk_created:
                commands.append(
                    self._gcloud(
                        "compute",
                        "disks",
                        "delete",
                        disk,
                        "--project",
                        self.config.project,
                        "--zone",
                        self.config.zone,
                        "--quiet",
                    )
                )
            if snapshot_created:
                commands.append(
                    self._gcloud(
                        "compute",
                        "snapshots",
                        "delete",
                        snapshot,
                        "--project",
                        self.config.project,
                        "--quiet",
                    )
                )
            self._cleanup_commands("notebook_volume", commands)

    def run(self) -> tuple[dict[str, Any], Path]:
        started = utc_now()
        evidence: dict[str, Any] = {
            "schema_version": "1",
            "drill_id": self.drill_id,
            "environment": self.config.environment,
            "project": self.config.project,
            "operator": self.config.operator,
            "ticket": self.config.ticket,
            "started_at": iso_time(started),
            "objectives": {"rpo_seconds": RPO_SECONDS, "rto_seconds": RTO_SECONDS},
            "exercises": {},
        }
        preflight_started = time.monotonic()
        preflight_passed = False
        try:
            preflight_result = self.preflight()
            preflight_result["status"] = "passed"
            preflight_passed = True
        except Exception as exc:
            preflight_result = {"status": "failed", "error": str(exc)}
        preflight_result["duration_seconds"] = round(time.monotonic() - preflight_started, 3)
        evidence["exercises"]["preflight"] = preflight_result

        exercises = [
            ("cloud_sql", self.cloud_sql),
            ("object_version", self.object_version),
            ("terraform_state", self.terraform_state),
            ("notebook_volume", self.notebook_volume),
        ]
        failed = not preflight_passed
        if preflight_passed:
            for name, exercise in exercises:
                step_started = time.monotonic()
                try:
                    result = exercise()
                except Exception as exc:
                    failed = True
                    result = {"status": "failed", "error": str(exc)}
                result["duration_seconds"] = round(time.monotonic() - step_started, 3)
                evidence["exercises"][name] = result
        else:
            for name, _ in exercises:
                evidence["exercises"][name] = {
                    "status": "skipped",
                    "reason": "preflight failed before cloud mutations",
                    "duration_seconds": 0,
                }

        evidence["finished_at"] = iso_time(utc_now())
        evidence["status"] = "failed" if failed else "passed"
        evidence["cleanup"] = self.cleanup
        self.config.evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence_path = self.config.evidence_dir / f"{self.drill_id}.json"
        evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")

        evidence_uri = (
            f"gs://{self.config.backup_bucket}/recovery-drills/{self.drill_id}/evidence.json"
        )
        if preflight_passed:
            try:
                self.runner.run(
                    self._gcloud(
                        "storage",
                        "cp",
                        str(evidence_path),
                        evidence_uri,
                        "--if-generation-match=0",
                    )
                )
                evidence["evidence_uri"] = evidence_uri
            except Exception as exc:
                evidence["status"] = "failed"
                evidence["evidence_upload"] = {"status": "failed", "error": str(exc)}
        evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
        return evidence, evidence_path


def plan(config: DrillConfig, drill_id: str) -> dict[str, Any]:
    config.validate()
    safe_drill_id(drill_id)
    return {
        "drill_id": drill_id,
        "environment": config.environment,
        "project": config.project,
        "mutations": [
            f"create and delete a PITR clone of {config.source_sql_instance}",
            f"restore a canary only under gs://{config.data_bucket}/recovery-drills/{drill_id}/",
            f"copy one noncurrent {config.state_prefix} state generation to an isolated drill key",
            f"snapshot and restore {config.notebook_instance} to a temporary disk",
            f"append evidence under gs://{config.backup_bucket}/recovery-drills/{drill_id}/",
        ],
        "production_resources": "forbidden",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "run"))
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", default="us-central1")
    parser.add_argument("--zone", default="us-central1-a")
    parser.add_argument("--data-bucket", required=True)
    parser.add_argument("--backup-bucket", required=True)
    parser.add_argument("--state-bucket", required=True)
    parser.add_argument("--state-prefix", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--drill-id", default=None)
    parser.add_argument("--evidence-dir", type=Path, default=Path("recovery-evidence"))
    parser.add_argument("--confirm-project")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    config = DrillConfig(
        project=args.project,
        region=args.region,
        zone=args.zone,
        data_bucket=args.data_bucket,
        backup_bucket=args.backup_bucket,
        state_bucket=args.state_bucket,
        state_prefix=args.state_prefix,
        image=args.image,
        operator=args.operator,
        ticket=args.ticket,
        evidence_dir=args.evidence_dir,
    )
    drill_id = safe_drill_id(args.drill_id or new_drill_id())
    try:
        if args.action == "plan":
            print(json.dumps(plan(config, drill_id), indent=2, sort_keys=True))
            return
        if args.confirm_project != config.project:
            raise DrillError("run requires --confirm-project matching the non-production project")
        evidence, evidence_path = RecoveryDrill(config, drill_id, CommandRunner()).run()
        print(f"evidence: {evidence_path}")
        if evidence["status"] != "passed":
            raise DrillError("one or more recovery exercises failed; inspect the evidence file")
    except DrillError as exc:
        print(f"recovery drill refused or failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
