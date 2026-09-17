"""Executable dependency rules for jobs and delivery tooling."""

import ast
from pathlib import Path


def test_jobs_do_not_depend_on_control_cli() -> None:
    for path in Path("jobs").rglob("*.py"):
        tree = ast.parse(path.read_text())
        imports = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        assert not any(name == "ctl" or name.startswith("ctl.") for name in imports), path


def test_deploy_never_copies_the_local_env_file() -> None:
    source = Path("ctl/commands/deploy.py").read_text()
    assert "ENV_FILE" not in source
    assert "runtime.env" in source


def test_control_compose_contains_only_secret_references() -> None:
    source = Path("compose/control.yml").read_text()
    assert "AIRFLOW_DB_PASSWORD" not in source
    assert "AIRFLOW_FERNET_KEY" not in source
    assert "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN:" not in source
    assert "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN_SECRET:" in source
    assert "AIRFLOW__CORE__FERNET_KEY_SECRET:" in source


def test_gcp_vms_use_only_immutable_host_images() -> None:
    source = Path("terraform/gcp/compute.tf").read_text()
    assert "metadata_startup_script" not in source
    assert "apt-get" not in source
    assert "debian-cloud/debian-12" not in source
    for role in ("control", "feed", "notebook"):
        assert f"image = var.host_images.{role}" in source


def test_gcp_host_builder_stays_private_and_pinned() -> None:
    source = Path("packer/gcp/host.pkr.hcl").read_text()
    assert 'required_version = ">= 1.16.0, < 2.0.0"' in source
    assert 'version = "= 1.2.7"' in source
    assert "source_image_family" not in source
    assert "\n  image_family" not in source
    assert "omit_external_ip                = true" in source
    assert "use_internal_ip                 = true" in source
    assert "use_iap                         = true" in source
    assert "disable_default_service_account = true" in source
    assert "docker_repo_key_sha256" in source
    assert "ops_agent_installer_sha256" in source
    assert "rsync_version" in source


def test_host_image_credentials_remain_in_ignored_env_file() -> None:
    ignore = Path(".gitignore").read_text()
    example = Path("packer/gcp/.env.image.example").read_text()
    assert ".env.*" in ignore
    assert "!packer/gcp/.env.image.example" in ignore
    assert "GOOGLE_APPLICATION_CREDENTIALS=" not in example
