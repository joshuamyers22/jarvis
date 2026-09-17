mock_provider "google" {
  mock_resource "google_monitoring_notification_channel" {
    defaults = {
      name = "projects/jarvis-research-prod/notificationChannels/123456789"
    }
  }
  mock_data "google_project" {
    defaults = {
      number          = "1234567892"
      billing_account = "000000-000000-000000"
    }
  }
}
mock_provider "random" {}

variables {
  project_id                 = "jarvis-research-prod"
  bucket_name                = "jarvis-research-prod-data"
  airflow_log_bucket_name    = "jarvis-research-prod-airflow-logs"
  scratch_bucket_name        = "jarvis-research-prod-scratch"
  backup_bucket_name         = "jarvis-research-prod-backup"
  billing_account_id         = "000000-000000-000000"
  alert_email                = "operations@example.com"
  monthly_budget_usd         = 5000
  deployer_principals        = ["group:platform@example.com"]
  operator_principals        = ["group:operators@example.com"]
  github_repository          = "example/jarvis"
  github_repository_id       = "123456789"
  github_repository_owner_id = "987654321"
}

run "production_boundary" {
  command = plan

  assert {
    condition     = output.environment == "prod"
    error_message = "The production root must not target another environment."
  }

  assert {
    condition     = output.state_prefix == "environments/prod"
    error_message = "Production state must use its dedicated prefix."
  }

  assert {
    condition     = output.project_id == "jarvis-research-prod"
    error_message = "The configured production project must reach the platform module unchanged."
  }

  assert {
    condition = (
      output.storage_locations.data == "gs://jarvis-research-prod-data" &&
      output.storage_locations.airflow_logs == "gs://jarvis-research-prod-airflow-logs" &&
      output.storage_locations.scratch == "gs://jarvis-research-prod-scratch" &&
      output.storage_locations.backup == "gs://jarvis-research-prod-backup" &&
      length(output.storage_contract.backup.workload_roles) == 0
    )
    error_message = "Production must keep data, logs, scratch, and backup in separate storage boundaries."
  }

  assert {
    condition = (
      output.storage_lifecycle_policy.raw.transition_after_days == 90 &&
      output.storage_lifecycle_policy.airflow_logs.delete_after_days == 90 &&
      output.storage_lifecycle_policy.scratch.delete_after_days == 14 &&
      output.storage_lifecycle_policy.noncurrent_data_versions.retained_count == 3 &&
      output.storage_lifecycle_policy.noncurrent_data_versions.minimum_age_days == 30 &&
      output.storage_lifecycle_policy.backup.delete_after_days == null
    )
    error_message = "Production must inherit the approved storage lifecycle policy."
  }

  assert {
    condition = (
      output.configuration.db_availability_type == "REGIONAL" &&
      output.configuration.db_deletion_protection &&
      output.database_policy.availability_type == "REGIONAL" &&
      !output.database_policy.connectivity.public_ipv4 &&
      output.database_policy.connectivity.ssl_mode == "ENCRYPTED_ONLY" &&
      output.database_policy.storage.type == "PD_SSD" &&
      output.database_policy.storage.autoresize &&
      output.database_policy.backups.enabled &&
      output.database_policy.backups.start_time_utc == "07:00" &&
      output.database_policy.backups.retained_count == 8 &&
      output.database_policy.backups.retention_unit == "COUNT" &&
      output.database_policy.point_in_time_recovery.enabled &&
      output.database_policy.point_in_time_recovery.transaction_log_retention_days == 7 &&
      output.database_policy.maintenance.day_utc == 7 &&
      output.database_policy.maintenance.hour_utc == 8 &&
      output.database_policy.maintenance.update_track == "week5" &&
      output.database_policy.query_insights.enabled &&
      output.database_policy.query_insights.plans_per_minute == 5 &&
      output.database_policy.query_insights.query_string_length == 1024 &&
      output.database_policy.query_insights.record_application_tags &&
      !output.database_policy.query_insights.record_client_address &&
      output.database_policy.deletion_protection.terraform &&
      output.database_policy.deletion_protection.api &&
      output.database_policy.recovery_objectives.rpo_minutes == 5 &&
      output.database_policy.recovery_objectives.rto_minutes == 120 &&
      output.database_policy.recovery_objectives.status == "provisional-pending-p2.5-restore-benchmark"
    )
    error_message = "Production must enforce the complete regional, private, recoverable Cloud SQL policy."
  }

  assert {
    condition = (
      output.configuration.workload_deletion_protection &&
      output.guardrails.budget.monthly_amount_usd == 5000 &&
      output.guardrails.quota_alerts.warning_threshold == 0.8 &&
      output.guardrails.deletion_protection.cloud_sql &&
      output.guardrails.deletion_protection.cloud_run_job &&
      alltrue(values(output.guardrails.deletion_protection.compute))
    )
    error_message = "Production guardrails must protect workloads and enforce its approved budget and quota alerts."
  }

  assert {
    condition = (
      length(output.guardrails.enabled_services) == 19 &&
      contains(output.guardrails.enabled_services, "bigquery.googleapis.com") &&
      contains(output.guardrails.enabled_services, "billingbudgets.googleapis.com") &&
      contains(output.guardrails.enabled_services, "monitoring.googleapis.com") &&
      contains(output.guardrails.enabled_services, "storage.googleapis.com") &&
      output.guardrails.audit_logging.service == "allServices" &&
      toset(output.guardrails.audit_logging.log_types) == toset(["ADMIN_READ", "DATA_READ", "DATA_WRITE"]) &&
      output.guardrails.resource_labels.platform["environment"] == "prod" &&
      output.guardrails.resource_labels.network["environment"] == "prod"
    )
    error_message = "Production must carry the complete API, audit, and labeling baseline."
  }

  assert {
    condition = (
      output.data_access_contract.default_deny &&
      length(output.data_access_contract.storage) == 0 &&
      length(output.data_access_contract.bigquery) == 0 &&
      length(output.data_access_contract.bigquery_job_users) == 0
    )
    error_message = "Production must deny cross-project data access unless its env file declares reviewed resources."
  }

  assert {
    condition     = output.network.subnet_cidr == "10.30.0.0/20" && output.network.private_service_cidr == "10.30.240.0/20"
    error_message = "Production must use its dedicated, non-overlapping address ranges."
  }

  assert {
    condition = (
      !output.network.security.auto_create_subnetworks &&
      output.network.security.private_ip_google_access &&
      output.network.security.nat_enabled &&
      output.network.security.vpc_flow_logs_enabled &&
      output.network.security.nat_error_logging_enabled
    )
    error_message = "The private VPC must keep explicit subnets, private Google access, NAT, and network logging."
  }

  assert {
    condition = (
      toset(output.network.security.iap_ssh_source_ranges) == toset(["35.235.240.0/20"]) &&
      toset(output.network.security.iap_ssh_ports) == toset(["22"]) &&
      toset(output.network.security.default_deny_source_ranges) == toset(["0.0.0.0/0"]) &&
      output.network.security.default_deny_protocol == "all" &&
      output.network.security.private_dns_visibility == "private"
    )
    error_message = "Ingress must be denied by default with SSH limited to IAP and DNS limited to the VPC."
  }

  assert {
    condition = (
      output.compute_networking.external_access_config_count == {
        control  = 0
        feed     = 0
        notebook = 0
      } &&
      output.compute_networking.os_login_enabled &&
      output.compute_networking.project_ssh_keys_blocked
    )
    error_message = "Compute instances must have private-only NICs and hardened SSH metadata."
  }

  assert {
    condition = toset(values(output.private_dns_records)) == toset([
      "control.prod.jarvis.internal.",
      "feed.prod.jarvis.internal.",
      "notebook.prod.jarvis.internal.",
    ])
    error_message = "Every private instance must receive an environment-local DNS record."
  }

  assert {
    condition = (
      output.github_oidc.repository_id == "123456789" &&
      output.github_oidc.repository_owner_id == "987654321" &&
      output.github_oidc.environment == "production" &&
      output.github_oidc.ref == "refs/heads/main"
    )
    error_message = "Production federation must be bound to the exact repository, production environment, and main branch."
  }
}

run "development_project_is_rejected" {
  command = plan

  variables {
    project_id = "jarvis-research-dev"
  }

  expect_failures = [var.project_id]
}

run "foreign_zone_is_rejected" {
  command = plan

  variables {
    zone = "us-east1-b"
  }

  expect_failures = [check.zone_region_boundary]
}
