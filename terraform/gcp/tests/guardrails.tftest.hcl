mock_provider "google" {
  mock_resource "google_service_account" {
    defaults = {
      email = "mock-identity@jarvis-research-dev.iam.gserviceaccount.com"
      name  = "projects/jarvis-research-dev/serviceAccounts/mock-identity@jarvis-research-dev.iam.gserviceaccount.com"
    }
  }

  mock_resource "google_iam_workload_identity_pool" {
    defaults = {
      name = "projects/1234567890/locations/global/workloadIdentityPools/research-dev-github"
    }
  }

  mock_resource "google_project_iam_custom_role" {
    defaults = {
      name = "projects/jarvis-research-dev/roles/jarvisInstancePower"
    }
  }

  mock_resource "google_monitoring_notification_channel" {
    defaults = {
      name = "projects/jarvis-research-dev/notificationChannels/123456789"
    }
  }

  mock_data "google_project" {
    defaults = {
      number          = "1234567890"
      billing_account = "000000-000000-000000"
    }
  }
}
mock_provider "random" {}

variables {
  project_id                   = "jarvis-research-dev"
  env                          = "dev"
  bucket_name                  = "jarvis-research-dev-data"
  airflow_log_bucket_name      = "jarvis-research-dev-airflow-logs"
  scratch_bucket_name          = "jarvis-research-dev-scratch"
  backup_bucket_name           = "jarvis-research-dev-backup"
  billing_account_id           = "000000-000000-000000"
  alert_email                  = "operations@example.com"
  monthly_budget_usd           = 500
  db_deletion_protection       = false
  network_self_link            = "projects/jarvis-research-dev/global/networks/research-dev-vpc"
  subnetwork_self_link         = "projects/jarvis-research-dev/regions/us-central1/subnetworks/research-dev-workloads"
  deployer_principals          = ["group:platform@example.com"]
  operator_principals          = ["group:operators@example.com"]
  github_repository            = "example/jarvis"
  github_repository_id         = "123456789"
  github_repository_owner_id   = "987654321"
  github_environment           = "development"
  workload_deletion_protection = false
  labels = {
    owner       = "platform"
    cost_center = "research"
    environment = "prod"
  }
}

run "project_guardrail_contract" {
  command = apply

  assert {
    condition = toset(output.guardrails.enabled_services) == toset([
      "artifactregistry.googleapis.com",
      "billingbudgets.googleapis.com",
      "bigquery.googleapis.com",
      "cloudbilling.googleapis.com",
      "cloudresourcemanager.googleapis.com",
      "iam.googleapis.com",
      "iamcredentials.googleapis.com",
      "logging.googleapis.com",
      "monitoring.googleapis.com",
      "run.googleapis.com",
      "secretmanager.googleapis.com",
      "serviceusage.googleapis.com",
      "sqladmin.googleapis.com",
      "storage.googleapis.com",
      "sts.googleapis.com",
    ])
    error_message = "Every platform, identity, billing, logging, and monitoring API must be explicit."
  }

  assert {
    condition = (
      output.guardrails.labels["application"] == "jarvis" &&
      output.guardrails.labels["component"] == "research-platform" &&
      output.guardrails.labels["environment"] == "dev" &&
      output.guardrails.labels["managed_by"] == "terraform" &&
      output.guardrails.labels["owner"] == "platform" &&
      output.guardrails.labels["cost_center"] == "research"
    )
    error_message = "Required identity labels must override callers while retaining ownership and cost labels."
  }

  assert {
    condition = (
      output.guardrails.audit_logging.service == "allServices" &&
      toset(output.guardrails.audit_logging.log_types) == toset(["ADMIN_READ", "DATA_READ", "DATA_WRITE"]) &&
      length(output.guardrails.audit_logging.exemptions) == 0
    )
    error_message = "All Data Access audit categories must be enabled globally without principal exemptions."
  }

  assert {
    condition = (
      output.guardrails.budget.billing_account == "000000-000000-000000" &&
      output.guardrails.budget.monthly_amount_usd == 500 &&
      length(output.guardrails.budget.thresholds) == 4 &&
      toset(google_billing_budget.environment.budget_filter[0].projects) == toset(["projects/1234567890"]) &&
      toset(google_billing_budget.environment.all_updates_rule[0].monitoring_notification_channels) == toset([google_monitoring_notification_channel.operations_email.name]) &&
      !google_billing_budget.environment.all_updates_rule[0].disable_default_iam_recipients
    )
    error_message = "The budget must be project-scoped, thresholded, and routed to both custom and default recipients."
  }

  assert {
    condition = (
      google_monitoring_notification_channel.operations_email.type == "email" &&
      google_monitoring_notification_channel.operations_email.labels["email_address"] == "operations@example.com" &&
      google_monitoring_alert_policy.quota_utilization.severity == "WARNING" &&
      strcontains(google_monitoring_alert_policy.quota_utilization.conditions[0].condition_prometheus_query_language[0].query, "> 0.8") &&
      google_monitoring_alert_policy.quota_exceeded.severity == "ERROR" &&
      google_monitoring_alert_policy.quota_exceeded.conditions[0].condition_threshold[0].filter == "metric.type=\"serviceruntime.googleapis.com/quota/exceeded\" AND resource.type=\"consumer_quota\""
    )
    error_message = "Quota utilization and quota-exceeded alerts must notify the operations channel."
  }

  assert {
    condition = (
      !output.guardrails.deletion_protection.cloud_sql &&
      !output.guardrails.deletion_protection.cloud_run_job &&
      alltrue([for protected in values(output.guardrails.deletion_protection.compute) : !protected]) &&
      !output.guardrails.deletion_protection.bucket_force_destroy &&
      alltrue([for force_destroy in values(output.guardrails.deletion_protection.storage_force_destroy) : !force_destroy])
    )
    error_message = "Development must be disposable explicitly while destructive bucket deletion remains disabled."
  }

  assert {
    condition = alltrue(flatten([
      for instance in values(output.guardrails.shielded_compute) :
      [instance.secure_boot, instance.vtpm, instance.integrity_monitoring]
    ]))
    error_message = "Every VM must enable the full Shielded VM baseline before the matching organization policy is enforced."
  }

  assert {
    condition = (
      contains(output.guardrails.organization_policies.required, "constraints/iam.managed.disableServiceAccountKeyCreation") &&
      contains(output.guardrails.organization_policies.required, "constraints/compute.vmExternalIpAccess") &&
      contains(output.guardrails.organization_policies.required, "constraints/compute.requireShieldedVm") &&
      contains(output.guardrails.organization_policies.optional, "constraints/iam.allowedPolicyMemberDomains") &&
      output.guardrails.external_iam.role == "roles/billing.costsManager"
    )
    error_message = "Required/optional organization controls and the external billing-account grant must be explicit."
  }

  assert {
    condition = (
      contains(local.deployer_project_roles, "roles/monitoring.editor") &&
      !contains(local.deployer_project_roles, "roles/owner") &&
      !contains(local.deployer_project_roles, "roles/editor")
    )
    error_message = "The deployer must manage project monitoring without basic Owner or Editor roles."
  }
}

run "invalid_budget_is_rejected" {
  command = plan

  variables {
    monthly_budget_usd = 0
  }

  expect_failures = [var.monthly_budget_usd]
}

run "invalid_quota_threshold_is_rejected" {
  command = plan

  variables {
    quota_warning_threshold = 1
  }

  expect_failures = [var.quota_warning_threshold]
}

run "invalid_alert_recipient_is_rejected" {
  command = plan

  variables {
    alert_email = "shared-account"
  }

  expect_failures = [var.alert_email]
}

run "foreign_billing_account_is_rejected" {
  command = plan

  variables {
    billing_account_id = "111111-111111-111111"
  }

  expect_failures = [check.billing_account_boundary]
}
