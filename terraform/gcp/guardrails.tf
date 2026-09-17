# Project-level controls that every environment must carry. Organization policy
# stays in the organization landing-zone stack because the environment deployer
# must never receive organization-wide policy administration.

locals {
  budget_thresholds = [
    { percent = 0.5, basis = "CURRENT_SPEND" },
    { percent = 0.8, basis = "CURRENT_SPEND" },
    { percent = 1.0, basis = "CURRENT_SPEND" },
    { percent = 1.0, basis = "FORECASTED_SPEND" },
  ]

  required_organization_policies = toset([
    "constraints/compute.disableSerialPortAccess",
    "constraints/compute.requireOsLogin",
    "constraints/compute.requireShieldedVm",
    "constraints/compute.skipDefaultNetworkCreation",
    "constraints/compute.vmExternalIpAccess",
    "constraints/iam.managed.disableServiceAccountKeyCreation",
    "constraints/iam.managed.disableServiceAccountKeyUpload",
    "constraints/iam.managed.preventPrivilegedBasicRolesForDefaultServiceAccounts",
    "constraints/sql.restrictPublicIp",
    "constraints/storage.publicAccessPrevention",
    "constraints/storage.uniformBucketLevelAccess",
  ])

  optional_organization_policies = toset([
    "constraints/compute.restrictSharedVpcSubnetworks",
    "constraints/compute.restrictVpcPeering",
    "constraints/gcp.resourceLocations",
    "constraints/iam.allowedPolicyMemberDomains",
  ])
}

data "google_project" "current" {
  project_id = var.project_id
}

check "billing_account_boundary" {
  assert {
    condition = (
      trimprefix(data.google_project.current.billing_account, "billingAccounts/") ==
      var.billing_account_id
    )
    error_message = "billing_account_id must be the billing account linked to project_id."
  }
}

# ADMIN_WRITE audit logs are always on in Google Cloud. This default policy
# explicitly enables the three Data Access categories for every current and
# future service, with no exempted principals.
resource "google_project_iam_audit_config" "all_services" {
  project = var.project_id
  service = "allServices"

  audit_log_config {
    log_type = "ADMIN_READ"
  }
  audit_log_config {
    log_type = "DATA_READ"
  }
  audit_log_config {
    log_type = "DATA_WRITE"
  }

  depends_on = [google_project_service.required]
}

resource "google_monitoring_notification_channel" "operations_email" {
  project      = var.project_id
  display_name = "Jarvis ${var.env} operations"
  description  = "Budget and quota alerts for the Jarvis ${var.env} environment."
  type         = "email"
  enabled      = true

  labels = {
    email_address = var.alert_email
  }
  user_labels = local.common_labels

  depends_on = [google_project_service.required]
}

resource "google_billing_budget" "environment" {
  billing_account = var.billing_account_id
  display_name    = "Jarvis ${var.env} monthly budget"
  ownership_scope = "BILLING_ACCOUNT"

  budget_filter {
    projects               = ["projects/${data.google_project.current.number}"]
    calendar_period        = "MONTH"
    credit_types_treatment = "INCLUDE_ALL_CREDITS"
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.monthly_budget_usd)
    }
  }

  dynamic "threshold_rules" {
    for_each = local.budget_thresholds
    content {
      threshold_percent = threshold_rules.value.percent
      spend_basis       = threshold_rules.value.basis
    }
  }

  all_updates_rule {
    monitoring_notification_channels = [google_monitoring_notification_channel.operations_email.name]
    disable_default_iam_recipients   = false
  }

  depends_on = [google_project_service.required]
}

# Warn before allocation quotas are exhausted. Cloud Monitoring evaluates the
# ratio independently for every project, quota metric, and location.
resource "google_monitoring_alert_policy" "quota_utilization" {
  project      = var.project_id
  display_name = "Jarvis ${var.env}: allocation quota above ${var.quota_warning_threshold * 100}%"
  combiner     = "OR"
  enabled      = true
  severity     = "WARNING"
  user_labels  = local.common_labels

  notification_channels = [google_monitoring_notification_channel.operations_email.name]

  conditions {
    display_name = "Any allocation quota approaches its limit"
    condition_prometheus_query_language {
      query = <<-EOT
        (
          max by (project_id, quota_metric, location) ({"serviceruntime.googleapis.com/quota/allocation/usage", monitored_resource="consumer_quota"})
          /
          min by (project_id, quota_metric, location) ({"serviceruntime.googleapis.com/quota/limit", monitored_resource="consumer_quota"})
        ) > ${var.quota_warning_threshold}
      EOT

      duration                  = "300s"
      evaluation_interval       = "60s"
      disable_metric_validation = true
    }
  }

  documentation {
    mime_type = "text/markdown"
    content   = "An allocation quota is approaching its configured limit. Identify the quota and either reduce demand or request a reviewed increase before workloads are throttled."
  }

  alert_strategy {
    auto_close           = "86400s"
    notification_prompts = ["OPENED", "CLOSED"]
  }

  depends_on = [google_project_service.required]
}

# The utilization warning covers allocation quotas. This second policy catches
# any supported rate or allocation quota once Google reports an exceeded event.
resource "google_monitoring_alert_policy" "quota_exceeded" {
  project      = var.project_id
  display_name = "Jarvis ${var.env}: quota exceeded"
  combiner     = "OR"
  enabled      = true
  severity     = "ERROR"
  user_labels  = local.common_labels

  notification_channels = [google_monitoring_notification_channel.operations_email.name]

  conditions {
    display_name = "Quota exceeded error by quota metric"
    condition_threshold {
      filter          = "metric.type=\"serviceruntime.googleapis.com/quota/exceeded\" AND resource.type=\"consumer_quota\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "60s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_COUNT_TRUE"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["metric.label.quota_metric"]
      }

      trigger {
        count = 1
      }
    }
  }

  documentation {
    mime_type = "text/markdown"
    content   = "Google Cloud rejected work because a quota was exhausted. Identify the affected quota, stabilize the workload, and request increases only after reviewing capacity and cost."
  }

  alert_strategy {
    auto_close           = "86400s"
    notification_prompts = ["OPENED", "CLOSED"]
  }

  depends_on = [google_project_service.required]
}
