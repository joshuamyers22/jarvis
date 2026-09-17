"""Declarative, non-secret runtime configuration and drift detection.

Terraform owns resource identities. Versioned TOML overlays own portable and
group-specific policy. The renderer combines those sources into a deterministic
env file plus a manifest that can be reproduced later without trusting the
rendered file itself.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ctl.commands._util import (
    DEPLOYMENT_ENV_KEYS,
    PROHIBITED_DEPLOYMENT_KEYS,
    REPO_ROOT,
)

SCHEMA_VERSION = 1
NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
LOCAL_CONFIGURATION_KEYS = frozenset({"CONTROL_HOST", "FEED_HOST", "NOTEBOOK_HOST"})
CONFIGURATION_KEYS = DEPLOYMENT_ENV_KEYS | LOCAL_CONFIGURATION_KEYS
TERRAFORM_MANAGED_KEYS = frozenset(
    {
        "IMAGE",
        "AIRFLOW_DB_HOST",
        "AIRFLOW_REMOTE_LOGS",
        "AIRFLOW_SECRETS_BACKEND",
        "AIRFLOW_SECRETS_KWARGS",
        "RP_ENV",
        "RP_CLOUD",
        "RP_PROJECT_ID",
        "RP_REGION",
        "RP_STORAGE_URI",
        "RP_SCRATCH_URI",
        "RP_BATCH_JOB_NAME",
        "RP_BATCH_JOB_QUEUE",
        "RP_RESOURCE_GROUP",
        "RP_SUBSCRIPTION_ID",
        "RP_AZURE_ACI_SUBNET_ID",
        "RP_AZURE_JOB_IDENTITY_ID",
        "RP_AZURE_KEY_VAULT_URI",
        "RP_VENDOR_CREDENTIAL_SECRET_ID",
        "RP_FEED_CREDENTIAL_SECRET_ID",
        "NOTEBOOKS_HOST_PATH",
        "CONTROL_HOST",
        "FEED_HOST",
        "NOTEBOOK_HOST",
    }
)


class ConfigurationError(RuntimeError):
    """A configuration source is invalid or no longer reproducible."""


@dataclass(frozen=True)
class ConfigurationStatus:
    current: bool
    fingerprint: str | None
    reasons: tuple[str, ...]
    manifest: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "current": self.current,
            "fingerprint": self.fingerprint,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class RenderedConfiguration:
    values: dict[str, str]
    fingerprint: str
    terraform_fingerprint: str
    manifest: dict[str, Any]


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        raise ConfigurationError(f"configuration file does not exist: {path}")
    for number, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        key, separator, value = line.partition("=")
        if not separator or not key.strip():
            raise ConfigurationError(f"invalid env syntax at {path}:{number}")
        normalized_key = key.strip()
        if normalized_key in values:
            raise ConfigurationError(f"duplicate env key at {path}:{number}: {normalized_key}")
        values[normalized_key] = value.strip().strip('"').strip("'")
    return values


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _source_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT))
    except ValueError:
        return str(resolved)


def _resolve_source(path: str) -> Path:
    source = Path(path)
    return source if source.is_absolute() else REPO_ROOT / source


def _string_value(key: str, value: Any, path: Path) -> str:
    if isinstance(value, bool):
        rendered = "true" if value else "false"
    elif isinstance(value, (str, int, float)):
        rendered = str(value)
    else:
        raise ConfigurationError(f"{path}: {key} must be a scalar value")
    if "\n" in rendered or "\r" in rendered:
        raise ConfigurationError(f"{path}: {key} must be a single-line value")
    return rendered


def _load_overlay(
    path: Path,
    environment: str,
    *,
    expected_kind: str | None = None,
    expected_name: str | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    if not path.exists():
        raise ConfigurationError(f"overlay does not exist: {path}")
    try:
        document = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"invalid TOML overlay {path}: {exc}") from exc
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ConfigurationError(f"{path}: schema_version must be {SCHEMA_VERSION}")
    allowed_tables = {"schema_version", "metadata", "platform", "runtime", "environments"}
    unknown_tables = sorted(set(document) - allowed_tables)
    if unknown_tables:
        raise ConfigurationError(f"{path}: unsupported sections: {', '.join(unknown_tables)}")

    metadata = document.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ConfigurationError(f"{path}: metadata must be a table")
    if expected_kind and metadata.get("kind") != expected_kind:
        raise ConfigurationError(f"{path}: metadata.kind must be {expected_kind!r}")
    if expected_kind == "group" and metadata.get("group") != expected_name:
        raise ConfigurationError(f"{path}: metadata.group must be {expected_name!r}")
    if expected_kind == "environment" and metadata.get("environment") != expected_name:
        raise ConfigurationError(f"{path}: metadata.environment must be {expected_name!r}")

    runtime = document.get("runtime", {})
    platform = document.get("platform", {})
    environments = document.get("environments", {})
    if not isinstance(runtime, dict) or not isinstance(platform, dict):
        raise ConfigurationError(f"{path}: runtime and platform must be tables")
    if not isinstance(environments, dict):
        raise ConfigurationError(f"{path}: environments must be a table")
    environment_values = environments.get(environment, {})
    if not isinstance(environment_values, dict):
        raise ConfigurationError(f"{path}: environments.{environment} must be a table")

    merged_runtime = {**runtime, **environment_values}
    prohibited = sorted(set(merged_runtime) & PROHIBITED_DEPLOYMENT_KEYS)
    if prohibited:
        raise ConfigurationError(f"{path}: secret values are prohibited: {', '.join(prohibited)}")
    unknown = sorted(set(merged_runtime) - CONFIGURATION_KEYS)
    if unknown:
        raise ConfigurationError(f"{path}: unsupported runtime keys: {', '.join(unknown)}")
    shadowed = sorted(set(merged_runtime) & TERRAFORM_MANAGED_KEYS)
    if shadowed:
        raise ConfigurationError(
            f"{path}: Terraform-managed keys cannot be overridden: {', '.join(shadowed)}"
        )
    unknown_platform = sorted(set(platform) - {"image_name"})
    if unknown_platform:
        raise ConfigurationError(
            f"{path}: unsupported platform keys: {', '.join(unknown_platform)}"
        )
    return (
        {key: _string_value(key, value, path) for key, value in merged_runtime.items()},
        {key: _string_value(key, value, path) for key, value in platform.items()},
    )


def _unwrap_outputs(raw: dict[str, Any]) -> dict[str, Any]:
    outputs: dict[str, Any] = {}
    for key, entry in raw.items():
        if isinstance(entry, dict) and "value" in entry:
            if entry.get("sensitive"):
                raise ConfigurationError(
                    f"Terraform output {key!r} is sensitive and cannot be rendered"
                )
            outputs[key] = entry["value"]
        else:
            outputs[key] = entry
    return outputs


def _required_output(outputs: dict[str, Any], key: str) -> Any:
    value = outputs.get(key)
    if value is None or value == "":
        raise ConfigurationError(f"Terraform output {key!r} is required")
    return value


def _terraform_values(
    raw_outputs: dict[str, Any], environment: str, image_name: str
) -> tuple[dict[str, str], str]:
    outputs = _unwrap_outputs(raw_outputs)
    output_environment = outputs.get("environment", environment)
    if output_environment != environment:
        raise ConfigurationError(
            f"Terraform environment {output_environment!r} does not match {environment!r}"
        )
    provider = outputs.get("provider")
    storage_uri = str(_required_output(outputs, "storage_uri"))
    if not provider:
        if storage_uri.startswith("gs://"):
            provider = "gcp"
        elif storage_uri.startswith("s3://"):
            provider = "aws"
        elif storage_uri.startswith(("abfs://", "abfss://", "az://")):
            provider = "azure"
    if provider not in {"gcp", "aws", "azure"}:
        raise ConfigurationError(f"unsupported Terraform provider: {provider!r}")

    configuration = outputs.get("configuration", {})
    instances = _required_output(outputs, "instances")
    if not isinstance(configuration, dict) or not isinstance(instances, dict):
        raise ConfigurationError("Terraform configuration and instances outputs must be objects")
    image = outputs.get("image_repository")
    if not image:
        registry = str(_required_output(outputs, "registry")).rstrip("/")
        if provider == "aws":
            image = registry
        elif provider == "azure":
            image = f"{registry}/research/{image_name}"
        else:
            image = f"{registry}/{image_name}"

    values = {
        "RP_ENV": environment,
        "RP_CLOUD": str(provider),
        "RP_STORAGE_URI": storage_uri,
        "RP_SCRATCH_URI": str(_required_output(outputs, "scratch_uri")),
        "AIRFLOW_REMOTE_LOGS": str(_required_output(outputs, "airflow_logs_uri")),
        "AIRFLOW_DB_HOST": str(_required_output(outputs, "db_host")),
        "AIRFLOW_SECRETS_BACKEND": str(_required_output(outputs, "airflow_secrets_backend")),
        "RP_BATCH_JOB_NAME": str(_required_output(outputs, "batch_job_name")),
        "IMAGE": str(image),
    }
    for role in ("control", "feed", "notebook"):
        if role not in instances:
            raise ConfigurationError(f"Terraform instances output lacks {role!r}")
        values[f"{role.upper()}_HOST"] = str(instances[role])

    region = configuration.get("region") or outputs.get("region")
    if region:
        values["RP_REGION"] = str(region)
    if provider == "gcp":
        project_id = str(_required_output(outputs, "project_id"))
        values["RP_PROJECT_ID"] = project_id
        values["AIRFLOW_SECRETS_KWARGS"] = json.dumps(
            {
                "project_id": project_id,
                "connections_prefix": "airflow-connections",
                "config_prefix": "airflow-config",
                "sep": "-",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        contract = outputs.get("runtime_secret_contract", {})
        if isinstance(contract, dict):
            for name, env_key in (
                ("vendor_credentials", "RP_VENDOR_CREDENTIAL_SECRET_ID"),
                ("feed_credentials", "RP_FEED_CREDENTIAL_SECRET_ID"),
            ):
                item = contract.get(name, {})
                if isinstance(item, dict) and item.get("secret_id"):
                    values[env_key] = str(item["secret_id"])
    elif provider == "aws":
        values["RP_BATCH_JOB_QUEUE"] = str(_required_output(outputs, "batch_job_queue"))
        notebook_efs = outputs.get("notebook_efs")
        if isinstance(notebook_efs, dict) and notebook_efs.get("host_mount_path"):
            values["NOTEBOOKS_HOST_PATH"] = str(notebook_efs["host_mount_path"])
        values["AIRFLOW_SECRETS_KWARGS"] = json.dumps(
            {
                "connections_prefix": "airflow/connections",
                "variables_prefix": "airflow/variables",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    else:
        values["RP_RESOURCE_GROUP"] = str(_required_output(outputs, "resource_group"))
        values["RP_SUBSCRIPTION_ID"] = str(_required_output(outputs, "subscription_id"))
        values["RP_AZURE_ACI_SUBNET_ID"] = str(_required_output(outputs, "aci_subnet_id"))
        values["RP_AZURE_JOB_IDENTITY_ID"] = str(_required_output(outputs, "job_identity_id"))
        values["RP_AZURE_KEY_VAULT_URI"] = str(_required_output(outputs, "key_vault_uri"))
        values["AIRFLOW_SECRETS_KWARGS"] = json.dumps(
            {
                "vault_url": values["RP_AZURE_KEY_VAULT_URI"],
                "connections_prefix": "airflow-connections",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    return values, _canonical_hash(values)


def render_configuration(
    raw_outputs: dict[str, Any],
    *,
    environment: str,
    group: str,
    overlays: list[Path],
    terraform_dir: Path,
    terraform_env_file: Path | None,
) -> RenderedConfiguration:
    if environment not in {"dev", "stage", "prod"}:
        raise ConfigurationError("environment must be dev, stage, or prod")
    if not NAME_PATTERN.fullmatch(group):
        raise ConfigurationError("group must use lowercase letters, numbers, dash, or underscore")

    base_path = REPO_ROOT / "config/runtime/base.toml"
    group_path = REPO_ROOT / f"config/runtime/groups/{group}.toml"
    environment_path = REPO_ROOT / f"config/runtime/environments/{environment}.toml"
    sources = [base_path, group_path, environment_path, *overlays]
    runtime: dict[str, str] = {}
    platform: dict[str, str] = {}
    for index, path in enumerate(sources):
        expected_kind = ("base", "group", "environment", None)[min(index, 3)]
        expected_name = group if index == 1 else environment if index == 2 else None
        runtime_values, platform_values = _load_overlay(
            path, environment, expected_kind=expected_kind, expected_name=expected_name
        )
        runtime.update(runtime_values)
        platform.update(platform_values)

    terraform_values, terraform_fingerprint = _terraform_values(
        raw_outputs, environment, platform.get("image_name", "base")
    )
    values = {**runtime, **terraform_values}
    if environment == "prod" and values.get("RP_FEED_WS_URL", "").endswith(".invalid/ws"):
        raise ConfigurationError("production group overlay must replace the example feed endpoint")
    missing = sorted(
        key
        for key in (
            "IMAGE",
            "AIRFLOW_DB_HOST",
            "AIRFLOW_REMOTE_LOGS",
            "RP_ENV",
            "RP_CLOUD",
            "RP_STORAGE_URI",
            "RP_SCRATCH_URI",
            "RP_REGION",
            "RP_FEED_WS_URL",
            "RP_FEED_SOURCE",
            "RP_FEED_DATASET",
        )
        if not values.get(key)
    )
    if missing:
        raise ConfigurationError("rendered configuration lacks: " + ", ".join(missing))

    configuration_values = {key: values[key] for key in sorted(values) if key in CONFIGURATION_KEYS}
    fingerprint = _canonical_hash(configuration_values)
    configuration_values["RP_CONFIG_FINGERPRINT"] = fingerprint
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "environment": environment,
        "group": group,
        "fingerprint": fingerprint,
        "terraform_fingerprint": terraform_fingerprint,
        "terraform_dir": _source_path(terraform_dir),
        "terraform_env_file": (
            _source_path(terraform_env_file) if terraform_env_file is not None else None
        ),
        "sources": [_source_path(path) for path in sources],
        "source_hashes": {
            _source_path(path): "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sources
        },
    }
    return RenderedConfiguration(configuration_values, fingerprint, terraform_fingerprint, manifest)


def terraform_output(terraform_dir: Path, terraform_env_file: Path | None) -> dict[str, Any]:
    command_env = dict(os.environ)
    if terraform_env_file is not None:
        command_env.update(parse_env_file(terraform_env_file))
    try:
        result = subprocess.run(
            ["terraform", f"-chdir={terraform_dir}", "output", "-json"],
            cwd=REPO_ROOT,
            env=command_env,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise ConfigurationError(f"could not execute terraform: {exc.strerror}") from exc
    if result.returncode:
        raise ConfigurationError(
            f"terraform output failed for {terraform_dir} with exit {result.returncode}"
        )
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("terraform output was not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ConfigurationError("terraform output must be a JSON object")
    return parsed


def write_configuration(rendered: RenderedConfiguration, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Generated by `ctl config render`; edit TOML overlays, not this file.",
        f"# fingerprint={rendered.fingerprint}",
    ]
    lines.extend(f"{key}={value}" for key, value in sorted(rendered.values.items()))
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text("\n".join(lines) + "\n")
    temporary.chmod(0o600)
    temporary.replace(output)
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    manifest_temp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    manifest_temp.write_text(json.dumps(rendered.manifest, indent=2, sort_keys=True) + "\n")
    manifest_temp.chmod(0o600)
    manifest_temp.replace(manifest_path)
    return manifest_path


def configuration_status(config_file: Path, *, refresh_terraform: bool) -> ConfigurationStatus:
    reasons: list[str] = []
    manifest_path = config_file.with_suffix(config_file.suffix + ".manifest.json")
    try:
        values = parse_env_file(config_file)
        manifest = json.loads(manifest_path.read_text())
        if not isinstance(manifest, dict):
            raise ConfigurationError("configuration manifest must be a JSON object")
        prohibited = sorted(set(values) & PROHIBITED_DEPLOYMENT_KEYS)
        if prohibited:
            raise ConfigurationError("generated configuration contains prohibited secret keys")
        unknown = sorted(set(values) - CONFIGURATION_KEYS)
        if unknown:
            raise ConfigurationError("generated configuration contains unsupported keys")
        fingerprint = values.get("RP_CONFIG_FINGERPRINT")
        if manifest.get("schema_version") != SCHEMA_VERSION:
            reasons.append("manifest-schema")
        if fingerprint != manifest.get("fingerprint"):
            reasons.append("rendered-file")
        comparable = {
            key: value
            for key, value in values.items()
            if key in CONFIGURATION_KEYS and key != "RP_CONFIG_FINGERPRINT"
        }
        if _canonical_hash(comparable) != fingerprint:
            reasons.append("rendered-file")
        source_hashes = manifest.get("source_hashes", {})
        if not isinstance(source_hashes, dict):
            raise ConfigurationError("manifest source_hashes must be an object")
        sources = manifest.get("sources")
        if (
            not isinstance(sources, list)
            or len(sources) < 3
            or not all(isinstance(source, str) for source in sources)
        ):
            raise ConfigurationError("manifest sources must contain the three base overlays")
        if set(source_hashes) != set(sources):
            raise ConfigurationError("manifest must hash every configuration source")
        for source, expected_hash in source_hashes.items():
            if not isinstance(source, str):
                raise ConfigurationError("manifest source path must be a string")
            path = _resolve_source(source)
            actual_hash = (
                "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
            )
            if actual_hash != expected_hash:
                reasons.append(f"overlay:{source}")

        if refresh_terraform:
            terraform_dir_value = manifest.get("terraform_dir")
            if not isinstance(terraform_dir_value, str):
                raise ConfigurationError("manifest terraform_dir must be a string")
            terraform_dir = _resolve_source(terraform_dir_value)
            env_file_value = manifest.get("terraform_env_file")
            if env_file_value is not None and not isinstance(env_file_value, str):
                raise ConfigurationError("manifest terraform_env_file must be a string or null")
            terraform_env_file = _resolve_source(env_file_value) if env_file_value else None
            raw_outputs = terraform_output(terraform_dir, terraform_env_file)
            source_paths = [_resolve_source(path) for path in sources]
            environment = manifest.get("environment")
            group = manifest.get("group")
            if not isinstance(environment, str) or not isinstance(group, str):
                raise ConfigurationError("manifest environment and group must be strings")
            rendered = render_configuration(
                raw_outputs,
                environment=environment,
                group=group,
                overlays=source_paths[3:],
                terraform_dir=terraform_dir,
                terraform_env_file=terraform_env_file,
            )
            if rendered.terraform_fingerprint != manifest.get("terraform_fingerprint"):
                reasons.append("terraform-state")
            if rendered.fingerprint != fingerprint:
                reasons.append("effective-configuration")
        return ConfigurationStatus(
            not reasons,
            fingerprint,
            tuple(dict.fromkeys(reasons)),
            manifest,
        )
    except (ConfigurationError, FileNotFoundError, KeyError, json.JSONDecodeError) as exc:
        return ConfigurationStatus(False, None, (f"invalid:{type(exc).__name__}",), None)


def configured_status(env: dict[str, str], *, refresh_terraform: bool) -> ConfigurationStatus:
    """Return the selected generated configuration's reproducibility state."""
    configured_path = env.get("RP_CONFIG_FILE")
    if not configured_path:
        return ConfigurationStatus(False, None, ("missing:RP_CONFIG_FILE",), None)
    path = Path(configured_path)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return configuration_status(path, refresh_terraform=refresh_terraform)


def require_current_configuration(
    env: dict[str, str], *, refresh_terraform: bool
) -> ConfigurationStatus | None:
    """Enforce generated configuration when selected, and always in production."""
    configured = bool(env.get("RP_CONFIG_FILE"))
    if not configured and env.get("RP_ENV") != "prod":
        return None
    status = configured_status(env, refresh_terraform=refresh_terraform)
    if not status.current:
        details = ", ".join(status.reasons) or "unknown drift"
        raise ConfigurationError(f"configuration is not current: {details}")
    if env.get("RP_CONFIG_FINGERPRINT") != status.fingerprint:
        raise ConfigurationError("loaded configuration fingerprint does not match its manifest")
    return status
