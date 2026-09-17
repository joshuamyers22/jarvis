from __future__ import annotations

import json
import stat
from pathlib import Path

import typer
from pytest import MonkeyPatch, raises

from ctl import configuration as configuration_module
from ctl.commands import _util
from ctl.configuration import (
    ConfigurationError,
    configuration_status,
    parse_env_file,
    render_configuration,
    require_current_configuration,
    write_configuration,
)


def _output(value, *, sensitive: bool = False):
    return {"sensitive": sensitive, "type": "string", "value": value}


def _gcp_outputs(environment: str = "dev") -> dict[str, object]:
    project = f"research-{environment}"
    return {
        "environment": _output(environment),
        "provider": _output("gcp"),
        "project_id": _output(project),
        "configuration": _output({"region": "us-central1"}),
        "storage_uri": _output(f"gs://{project}-data"),
        "scratch_uri": _output(f"gs://{project}-scratch"),
        "airflow_logs_uri": _output(f"gs://{project}-logs"),
        "registry": _output(f"us-central1-docker.pkg.dev/{project}/research"),
        "image_repository": _output(f"us-central1-docker.pkg.dev/{project}/research/base"),
        "batch_job_name": _output(f"research-{environment}-job"),
        "db_host": _output("10.10.0.3"),
        "instances": _output(
            {
                "control": f"research-{environment}-control",
                "feed": f"research-{environment}-feed",
                "notebook": f"research-{environment}-notebook",
            }
        ),
        "airflow_secrets_backend": _output(
            "airflow.providers.google.cloud.secrets.secret_manager.CloudSecretManagerBackend"
        ),
        "runtime_secret_contract": _output(
            {
                "vendor_credentials": {"secret_id": f"{project}-vendor"},
                "feed_credentials": {"secret_id": f"{project}-feed"},
            }
        ),
        "notebook_storage": _output(
            {
                "mode": "gcp-pd",
                "disk_name": f"research-{environment}-notebooks",
                "host_mount_path": "/mnt/jarvis-notebooks",
            }
        ),
    }


def _aws_outputs(environment: str = "dev", *, efs: bool = True) -> dict[str, object]:
    return {
        "environment": _output(environment),
        "provider": _output("aws"),
        "configuration": _output({"region": "us-east-1"}),
        "storage_uri": _output("s3://research-data"),
        "scratch_uri": _output("s3://research-scratch"),
        "airflow_logs_uri": _output("s3://research-logs"),
        "image_repository": _output("123456789012.dkr.ecr.us-east-1.amazonaws.com/base"),
        "batch_job_name": _output("research-job"),
        "batch_job_queue": _output("research-queue"),
        "db_host": _output("database.internal"),
        "instances": _output({"control": "i-control", "feed": "i-feed", "notebook": "i-notebook"}),
        "airflow_secrets_backend": _output(
            "airflow.providers.amazon.aws.secrets.secrets_manager.SecretsManagerBackend"
        ),
        "notebook_efs": _output(
            {
                "file_system_id": "fs-0123456789abcdef0",
                "access_point_id": "fsap-0123456789abcdef0",
                "host_mount_path": "/mnt/jarvis-notebooks",
            }
            if efs
            else None
        ),
    }


def _render(
    tmp_path: Path,
    *,
    environment: str = "dev",
    overlays: list[Path] | None = None,
):
    return render_configuration(
        _gcp_outputs(environment),
        environment=environment,
        group="default",
        overlays=overlays or [],
        terraform_dir=tmp_path / "terraform",
        terraform_env_file=None,
    )


def test_render_combines_versioned_policy_with_terraform_outputs(tmp_path: Path) -> None:
    rendered = _render(tmp_path)

    assert rendered.values["RP_ENV"] == "dev"
    assert rendered.values["RP_PROJECT_ID"] == "research-dev"
    assert rendered.values["RP_FEED_SOURCE"] == "example"
    assert rendered.values["CONTROL_HOST"] == "research-dev-control"
    assert rendered.values["RP_NOTEBOOK_STORAGE_MODE"] == "gcp-pd"
    assert rendered.values["RP_NOTEBOOK_STORAGE_ID"] == "research-dev-notebooks"
    assert rendered.values["NOTEBOOKS_HOST_PATH"] == "/mnt/jarvis-notebooks"
    assert rendered.values["RP_CONFIG_FINGERPRINT"] == rendered.fingerprint
    assert "AIRFLOW_DB_PASSWORD" not in rendered.values
    assert rendered.fingerprint.startswith("sha256:")


def test_group_extension_can_override_portable_values_by_environment(
    tmp_path: Path,
) -> None:
    overlay = tmp_path / "quant.toml"
    overlay.write_text(
        """schema_version = 1

[metadata]
kind = "extension"

[runtime]
RP_FEED_SOURCE = "quant-feed"

[environments.dev]
RP_FEED_DATASET = "sandbox-ticks"
"""
    )

    rendered = _render(tmp_path, overlays=[overlay])

    assert rendered.values["RP_FEED_SOURCE"] == "quant-feed"
    assert rendered.values["RP_FEED_DATASET"] == "sandbox-ticks"
    assert str(overlay) in rendered.manifest["sources"]


def test_aws_efs_identity_is_rendered_but_mount_policy_stays_in_terraform(
    tmp_path: Path,
) -> None:
    rendered = render_configuration(
        _aws_outputs(),
        environment="dev",
        group="default",
        overlays=[],
        terraform_dir=tmp_path,
        terraform_env_file=None,
    )

    assert rendered.values["RP_NOTEBOOK_STORAGE_MODE"] == "aws-efs"
    assert rendered.values["RP_NOTEBOOK_STORAGE_ID"] == "fs-0123456789abcdef0"
    assert rendered.values["RP_NOTEBOOK_STORAGE_ACCESS_POINT_ID"] == "fsap-0123456789abcdef0"


def test_production_aws_requires_durable_notebook_storage(tmp_path: Path) -> None:
    with raises(ConfigurationError, match="enable_notebook_efs"):
        render_configuration(
            _aws_outputs("prod", efs=False),
            environment="prod",
            group="default",
            overlays=[],
            terraform_dir=tmp_path,
            terraform_env_file=None,
        )


def test_overlay_cannot_replace_terraform_owned_or_secret_values(tmp_path: Path) -> None:
    managed = tmp_path / "managed.toml"
    managed.write_text(
        """schema_version = 1
[metadata]
kind = "extension"
[runtime]
RP_STORAGE_URI = "gs://wrong"
"""
    )
    with raises(ConfigurationError, match="Terraform-managed"):
        _render(tmp_path, overlays=[managed])

    secret = tmp_path / "secret.toml"
    secret.write_text(
        """schema_version = 1
[metadata]
kind = "extension"
[runtime]
AIRFLOW_DB_PASSWORD = "must-not-render"
"""
    )
    with raises(ConfigurationError, match="secret values are prohibited"):
        _render(tmp_path, overlays=[secret])


def test_production_rejects_placeholder_group_configuration(tmp_path: Path) -> None:
    with raises(ConfigurationError, match="example feed endpoint"):
        _render(tmp_path, environment="prod")


def test_manifest_detects_rendered_file_and_overlay_drift(tmp_path: Path) -> None:
    overlay = tmp_path / "team.toml"
    overlay.write_text(
        """schema_version = 1
[metadata]
kind = "extension"
[runtime]
RP_FEED_SOURCE = "team-feed"
"""
    )
    output = tmp_path / "runtime.env"
    rendered = _render(tmp_path, overlays=[overlay])
    manifest = write_configuration(rendered, output)

    assert configuration_status(output, refresh_terraform=False).current is True
    assert parse_env_file(output)["RP_CONFIG_FINGERPRINT"] == rendered.fingerprint
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert stat.S_IMODE(manifest.stat().st_mode) == 0o600

    overlay.write_text(overlay.read_text().replace("team-feed", "changed-feed"))
    status = configuration_status(output, refresh_terraform=False)
    assert status.current is False
    assert any(reason.startswith("overlay:") for reason in status.reasons)


def test_manifest_detects_terraform_drift(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    output = tmp_path / "runtime.env"
    rendered = _render(tmp_path)
    write_configuration(rendered, output)
    changed = _gcp_outputs()
    changed["storage_uri"] = _output("gs://research-dev-replacement")
    monkeypatch.setattr(
        configuration_module,
        "terraform_output",
        lambda terraform_dir, terraform_env_file: changed,
    )

    status = configuration_status(output, refresh_terraform=True)

    assert status.current is False
    assert "terraform-state" in status.reasons
    assert "effective-configuration" in status.reasons


def test_sensitive_terraform_output_is_never_rendered(tmp_path: Path) -> None:
    outputs = _gcp_outputs()
    outputs["unexpected_secret"] = _output("secret", sensitive=True)

    with raises(ConfigurationError, match="sensitive"):
        render_configuration(
            outputs,
            environment="dev",
            group="default",
            overlays=[],
            terraform_dir=tmp_path,
            terraform_env_file=None,
        )


def test_manifest_contains_no_terraform_values(tmp_path: Path) -> None:
    rendered = _render(tmp_path)
    serialized = json.dumps(rendered.manifest)

    assert "10.10.0.3" not in serialized
    assert "vendor" not in serialized


def test_local_env_selects_generated_config_without_silent_precedence(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    generated = tmp_path / "runtime.env"
    generated.write_text("RP_ENV=dev\nRP_STORAGE_URI=gs://generated\n")
    local = tmp_path / ".env"
    local.write_text(f"RP_CONFIG_FILE={generated}\nSSH_USER=operator\n")
    monkeypatch.setattr(_util, "ENV_FILE", local)

    loaded = _util.load_env()
    assert loaded["RP_STORAGE_URI"] == "gs://generated"
    assert loaded["SSH_USER"] == "operator"

    local.write_text(f"RP_CONFIG_FILE={generated}\nSSH_USER=operator\nRP_STORAGE_URI=gs://local\n")
    with raises(typer.Exit):
        _util.load_env()

    local.write_text(f"RP_CONFIG_FILE={generated}\nUNREVIEWED_SETTING=value\n")
    with raises(typer.Exit):
        _util.load_env()


def test_production_requires_generated_configuration() -> None:
    with raises(ConfigurationError, match="missing:RP_CONFIG_FILE"):
        require_current_configuration({"RP_ENV": "prod"}, refresh_terraform=False)

    assert require_current_configuration({"RP_ENV": "dev"}, refresh_terraform=False) is None
