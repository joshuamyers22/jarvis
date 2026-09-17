mock_provider "google" {
  mock_resource "google_monitoring_notification_channel" {
    defaults = {
      name = "projects/jarvis-research-stage/notificationChannels/123456789"
    }
  }
  mock_data "google_project" {
    defaults = {
      number          = "1234567891"
      billing_account = "000000-000000-000000"
    }
  }
}
mock_provider "random" {}

variables {
  project_id                 = "jarvis-research-stage"
  bucket_name                = "jarvis-research-stage-data"
  airflow_log_bucket_name    = "jarvis-research-stage-airflow-logs"
  scratch_bucket_name        = "jarvis-research-stage-scratch"
  backup_bucket_name         = "jarvis-research-stage-backup"
  billing_account_id         = "000000-000000-000000"
  alert_email                = "operations@example.com"
  monthly_budget_usd         = 1000
  deployer_principals        = ["group:platform@example.com"]
  operator_principals        = ["group:operators@example.com"]
  github_repository          = "example/jarvis"
  github_repository_id       = "123456789"
  github_repository_owner_id = "987654321"
}

run "staging_boundary" {
  command = plan

  assert {
    condition     = output.environment == "stage"
    error_message = "The staging root must not target another environment."
  }

  assert {
    condition     = output.state_prefix == "environments/stage"
    error_message = "Staging state must use its dedicated prefix."
  }

  assert {
    condition     = output.project_id == "jarvis-research-stage"
    error_message = "The configured staging project must reach the platform module unchanged."
  }

  assert {
    condition = (
      output.storage_locations.data == "gs://jarvis-research-stage-data" &&
      output.storage_locations.airflow_logs == "gs://jarvis-research-stage-airflow-logs" &&
      output.storage_locations.scratch == "gs://jarvis-research-stage-scratch" &&
      output.storage_locations.backup == "gs://jarvis-research-stage-backup" &&
      length(output.storage_contract.backup.workload_roles) == 0
    )
    error_message = "Staging must keep data, logs, scratch, and backup in separate storage boundaries."
  }

  assert {
    condition     = output.configuration.db_availability_type == "ZONAL" && output.configuration.db_deletion_protection
    error_message = "Staging must keep deletion protection while using a zonal database."
  }

  assert {
    condition = (
      output.configuration.workload_deletion_protection &&
      output.guardrails.budget.monthly_amount_usd == 1000 &&
      output.guardrails.quota_alerts.warning_threshold == 0.8 &&
      output.guardrails.deletion_protection.cloud_sql &&
      output.guardrails.deletion_protection.cloud_run_job &&
      alltrue(values(output.guardrails.deletion_protection.compute))
    )
    error_message = "Staging guardrails must protect workloads and enforce its approved budget and quota alerts."
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
      output.guardrails.resource_labels.platform["environment"] == "stage" &&
      output.guardrails.resource_labels.network["environment"] == "stage"
    )
    error_message = "Staging must carry the complete API, audit, and labeling baseline."
  }

  assert {
    condition = (
      output.data_access_contract.default_deny &&
      length(output.data_access_contract.storage) == 0 &&
      length(output.data_access_contract.bigquery) == 0 &&
      length(output.data_access_contract.bigquery_job_users) == 0
    )
    error_message = "Staging must deny cross-project data access unless its env file declares reviewed resources."
  }

  assert {
    condition     = output.network.subnet_cidr == "10.20.0.0/20" && output.network.private_service_cidr == "10.20.240.0/20"
    error_message = "Staging must use its dedicated, non-overlapping address ranges."
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
      "control.stage.jarvis.internal.",
      "feed.stage.jarvis.internal.",
      "notebook.stage.jarvis.internal.",
    ])
    error_message = "Every private instance must receive an environment-local DNS record."
  }

  assert {
    condition = (
      output.github_oidc.repository_id == "123456789" &&
      output.github_oidc.repository_owner_id == "987654321" &&
      output.github_oidc.environment == "staging" &&
      output.github_oidc.ref == "refs/heads/main"
    )
    error_message = "Staging federation must be bound to the exact repository, staging environment, and main branch."
  }
}

run "production_project_is_rejected" {
  command = plan

  variables {
    project_id = "jarvis-research-prod"
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
