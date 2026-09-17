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
    assert 'source      = "${path.root}/files/jarvis-compose"' in source
    assert 'source      = "${path.root}/files/jarvis-compose@.service"' in source


def test_gcp_systemd_is_the_bounded_compose_lifecycle_owner() -> None:
    unit = Path("packer/gcp/files/jarvis-compose@.service").read_text()
    supervisor = Path("packer/gcp/files/jarvis-compose").read_text()
    base_compose = "\n".join(
        Path(f"compose/{role}.yml").read_text() for role in ("control", "feed", "notebook")
    )
    systemd_compose = "\n".join(
        Path(f"compose/{role}.systemd.yml").read_text() for role in ("control", "feed", "notebook")
    )

    assert "WantedBy=multi-user.target" in unit
    assert "Restart=on-failure" in unit
    assert "StartLimitIntervalSec=300" in unit
    assert "StartLimitBurst=3" in unit
    assert "PartOf=docker.service" in unit
    assert "ExecStart=/usr/local/sbin/jarvis-compose supervise %i" in unit
    assert "RuntimeDirectory=jarvis-%i" in unit
    assert "NoNewPrivileges=true" in unit
    assert "health()" in supervisor
    assert 'json_health "$healthy"' in supervisor
    assert "metadata.google.internal" in supervisor
    assert "--connect-timeout 2" in supervisor
    assert "timeout --foreground" in supervisor
    assert "label=com.docker.compose.project=jarvis-${role}" in supervisor
    assert "systemd_compose_file" in supervisor
    assert "restart: always" in base_compose
    assert base_compose.count("restart: unless-stopped") == 2
    assert systemd_compose.count('restart: "no"') == 4


def test_database_migration_has_one_explicit_owner() -> None:
    entrypoint = Path("docker/entrypoint.sh").read_text()
    compose = Path("compose/control.yml").read_text()
    supervisor = Path("packer/gcp/files/jarvis-compose").read_text()
    dependencies = Path("pyproject.toml").read_text()
    scheduler_case = entrypoint.split("  scheduler)", 1)[1].split("    ;;", 1)[0]

    assert "airflow db migrate" not in scheduler_case
    assert "wait_for_migrations" in scheduler_case
    assert "airflow db migrate --use-migration-files" in entrypoint
    assert "timeout --foreground --kill-after=30s 1800s" in entrypoint
    assert 'profiles: ["migration"]' in compose
    assert 'command: ["migration"]' in compose
    assert "migration-preflight" in supervisor
    assert "migration-current" in supervisor
    assert "apache-airflow==3.3.*" in dependencies
    assert ".env.migration-pending" in Path("ctl/commands/migrate.py").read_text()
    assert ".env.migration-pending" in Path("ctl/commands/deploy.py").read_text()


def test_deployments_are_digest_pinned_and_transactional() -> None:
    deploy = Path("ctl/commands/deploy.py").read_text()
    supervisor = Path("packer/gcp/files/jarvis-compose").read_text()
    compose = "\n".join(
        Path(f"compose/{role}.yml").read_text() for role in ("control", "feed", "notebook")
    )

    assert compose.count("${IMAGE_DIGEST_SUFFIX:-}") == 3
    assert "candidate-preflight" in supervisor
    assert "RP_IMAGE_CLOUD" in supervisor
    assert "image-reference" in supervisor
    assert "compose.candidate" in supervisor
    assert ".env.previous-tag" in deploy
    assert "runtime.previous.env" in deploy
    assert "_run_synthetic_probe" in deploy
    assert "_collect_failure_logs" in deploy


def test_runtime_configuration_is_generated_and_drift_tracked() -> None:
    configuration = Path("ctl/configuration.py").read_text()
    deploy = Path("ctl/commands/deploy.py").read_text()
    release = Path("ctl/commands/release.py").read_text()
    ignore = Path(".gitignore").read_text()

    assert "terraform output" in configuration
    assert "PROHIBITED_DEPLOYMENT_KEYS" in configuration
    assert "RP_CONFIG_FINGERPRINT" in configuration
    assert "require_current_configuration" in deploy
    assert "_remote_configuration_fingerprint" in release
    assert ".runtime/" in ignore

    for provider in ("gcp", "aws", "azure"):
        outputs = Path(f"terraform/{provider}/outputs.tf").read_text()
        for name in ("environment", "provider", "configuration", "image_repository"):
            assert f'output "{name}"' in outputs


def test_host_image_credentials_remain_in_ignored_env_file() -> None:
    ignore = Path(".gitignore").read_text()
    example = Path("packer/gcp/.env.image.example").read_text()
    assert ".env.*" in ignore
    assert "!packer/gcp/.env.image.example" in ignore
    assert "GOOGLE_APPLICATION_CREDENTIALS=" not in example
