variable "project_id" {
  type        = string
  description = "GCP project id."

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a valid 6-30 character GCP project ID."
  }
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "zone" {
  type    = string
  default = "us-central1-a"
}

variable "env" {
  type        = string
  description = "Deployment environment. Live roots pass this as a literal."

  validation {
    condition     = contains(["dev", "stage", "prod"], var.env)
    error_message = "env must be dev, stage, or prod."
  }
}

variable "bucket_name" {
  type        = string
  description = "Globally unique data bucket name."

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$", var.bucket_name))
    error_message = "bucket_name must be a valid 3-63 character Cloud Storage bucket name."
  }
}

variable "airflow_log_bucket_name" {
  type        = string
  description = "Globally unique bucket dedicated to Airflow task logs."

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$", var.airflow_log_bucket_name))
    error_message = "airflow_log_bucket_name must be a valid 3-63 character Cloud Storage bucket name."
  }
}

variable "scratch_bucket_name" {
  type        = string
  description = "Globally unique bucket for temporary job and notebook scratch data."

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$", var.scratch_bucket_name))
    error_message = "scratch_bucket_name must be a valid 3-63 character Cloud Storage bucket name."
  }
}

variable "backup_bucket_name" {
  type        = string
  description = "Globally unique bucket reserved for backup and restore artifacts."

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$", var.backup_bucket_name))
    error_message = "backup_bucket_name must be a valid 3-63 character Cloud Storage bucket name."
  }

  validation {
    condition = length(toset([
      var.bucket_name,
      var.airflow_log_bucket_name,
      var.scratch_bucket_name,
      var.backup_bucket_name,
    ])) == 4
    error_message = "Data, Airflow-log, scratch, and backup buckets must use distinct names."
  }
}

variable "billing_account_id" {
  type        = string
  description = "Cloud Billing account that owns the environment budget."

  validation {
    condition     = can(regex("^[0-9A-F]{6}-[0-9A-F]{6}-[0-9A-F]{6}$", upper(var.billing_account_id)))
    error_message = "billing_account_id must use the XXXXXX-XXXXXX-XXXXXX format."
  }
}

variable "alert_email" {
  type        = string
  description = "Operational email recipient for budget and quota notifications."

  validation {
    condition     = can(regex("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", var.alert_email))
    error_message = "alert_email must be a valid email address."
  }
}

variable "monthly_budget_usd" {
  type        = number
  description = "Approved whole-dollar monthly budget for this environment."

  validation {
    condition     = var.monthly_budget_usd > 0 && floor(var.monthly_budget_usd) == var.monthly_budget_usd
    error_message = "monthly_budget_usd must be a positive whole-dollar amount."
  }
}

variable "quota_warning_threshold" {
  type        = number
  description = "Allocation quota utilization ratio that opens a warning incident."
  default     = 0.8

  validation {
    condition     = var.quota_warning_threshold >= 0.5 && var.quota_warning_threshold < 1
    error_message = "quota_warning_threshold must be at least 0.5 and less than 1.0."
  }
}

variable "labels" {
  type        = map(string)
  description = "Additional ownership and cost-allocation labels. Required identity labels cannot be overridden."
  default     = {}

  validation {
    condition = alltrue([
      for key, value in var.labels :
      can(regex("^[a-z][a-z0-9_-]{0,62}$", key)) &&
      can(regex("^[a-z0-9_-]{0,63}$", value))
    ])
    error_message = "Label keys and values must satisfy Google Cloud label syntax."
  }
}

variable "shared_storage_buckets" {
  type = map(object({
    project_id         = string
    source_environment = string
    location           = string
    owner              = string
    classification     = string
    approval_id        = string
    review_on          = string
    workload_access    = map(string)
  }))
  description = "Explicit cross-project Cloud Storage grants, keyed by globally unique bucket name."
  default     = {}

  validation {
    condition = alltrue([
      for bucket, config in var.shared_storage_buckets :
      can(regex("^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$", bucket)) &&
      can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", config.project_id)) &&
      config.project_id != var.project_id
    ])
    error_message = "Shared bucket names and project IDs must be valid, and a shared bucket must belong to another project."
  }

  validation {
    condition = alltrue([
      for config in values(var.shared_storage_buckets) :
      contains(["shared", var.env], config.source_environment) &&
      (
        length(regexall("-(dev|stage|prod)$", config.project_id)) == 0 ||
        endswith(config.project_id, "-${config.source_environment}")
      )
    ])
    error_message = "Shared buckets may come only from shared or same-environment projects; an environment suffix must match the declaration."
  }

  validation {
    condition = alltrue([
      for config in values(var.shared_storage_buckets) :
      contains([var.region, upper(split("-", var.region)[0])], config.location) &&
      can(regex("^group:[^[:space:]]+@[^[:space:]]+$", config.owner)) &&
      contains(["public", "internal", "confidential", "restricted"], config.classification) &&
      can(regex("^[A-Za-z0-9][A-Za-z0-9._/-]{2,127}$", config.approval_id)) &&
      can(formatdate("YYYY-MM-DD", "${config.review_on}T00:00:00Z")) &&
      length(config.workload_access) > 0
    ])
    error_message = "Every shared bucket needs an approved location, group owner, classification, approval ID, review date, and at least one grant."
  }

  validation {
    condition = alltrue(flatten([
      for config in values(var.shared_storage_buckets) : [
        for workload, access in config.workload_access :
        (workload == "job" && contains(["reader", "writer"], access)) ||
        (workload == "feed" && access == "creator") ||
        (workload == "notebook" && access == "reader")
      ]
    ]))
    error_message = "Storage grants allow job reader/writer, feed creator, and notebook reader only."
  }
}

variable "shared_bigquery_datasets" {
  type = map(object({
    project_id         = string
    dataset_id         = string
    source_environment = string
    location           = string
    owner              = string
    classification     = string
    approval_id        = string
    review_on          = string
    workload_access    = map(string)
  }))
  description = "Explicit cross-project BigQuery grants, keyed by a stable approval alias."
  default     = {}

  validation {
    condition = alltrue([
      for config in values(var.shared_bigquery_datasets) :
      can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", config.project_id)) &&
      can(regex("^[A-Za-z0-9_]+$", config.dataset_id)) &&
      length(config.dataset_id) <= 1024 &&
      config.project_id != var.project_id
    ])
    error_message = "Shared BigQuery project and dataset IDs must be valid, and a shared dataset must belong to another project."
  }

  validation {
    condition = length(distinct([
      for config in values(var.shared_bigquery_datasets) :
      "${config.project_id}/${config.dataset_id}"
    ])) == length(var.shared_bigquery_datasets)
    error_message = "Each external BigQuery dataset may appear only once."
  }

  validation {
    condition = alltrue([
      for config in values(var.shared_bigquery_datasets) :
      contains(["shared", var.env], config.source_environment) &&
      (
        length(regexall("-(dev|stage|prod)$", config.project_id)) == 0 ||
        endswith(config.project_id, "-${config.source_environment}")
      )
    ])
    error_message = "Shared datasets may come only from shared or same-environment projects; an environment suffix must match the declaration."
  }

  validation {
    condition = alltrue([
      for config in values(var.shared_bigquery_datasets) :
      contains([var.region, upper(split("-", var.region)[0])], config.location) &&
      can(regex("^group:[^[:space:]]+@[^[:space:]]+$", config.owner)) &&
      contains(["public", "internal", "confidential", "restricted"], config.classification) &&
      can(regex("^[A-Za-z0-9][A-Za-z0-9._/-]{2,127}$", config.approval_id)) &&
      can(formatdate("YYYY-MM-DD", "${config.review_on}T00:00:00Z")) &&
      length(config.workload_access) > 0
    ])
    error_message = "Every shared dataset needs an approved location, group owner, classification, approval ID, review date, and at least one grant."
  }

  validation {
    condition = alltrue(flatten([
      for config in values(var.shared_bigquery_datasets) : [
        for workload, access in config.workload_access :
        (workload == "job" && contains(["reader", "writer"], access)) ||
        (workload == "notebook" && access == "reader")
      ]
    ]))
    error_message = "BigQuery grants allow job reader/writer and notebook reader only."
  }
}

variable "network_self_link" {
  type        = string
  description = "Self-link of the existing VPC used by VMs and private service access."
}

variable "subnetwork_self_link" {
  type        = string
  description = "Self-link of the existing regional subnet used by platform VMs."
}

variable "db_tier" {
  type    = string
  default = "db-f1-micro"
}

variable "db_availability_type" {
  type        = string
  description = "Cloud SQL availability type. Production uses REGIONAL."
  default     = "ZONAL"

  validation {
    condition     = contains(["ZONAL", "REGIONAL"], var.db_availability_type)
    error_message = "db_availability_type must be ZONAL or REGIONAL."
  }
}

variable "db_deletion_protection" {
  type        = bool
  description = "Protect the Cloud SQL instance from accidental deletion in Terraform and the Cloud SQL API."
  default     = true
}

variable "db_backup_start_time" {
  type        = string
  description = "UTC start time for the daily Cloud SQL backup window in HH:MM format."
  default     = "07:00"

  validation {
    condition = (
      can(regex("^(?:[01][0-9]|2[0-3]):[0-5][0-9]$", var.db_backup_start_time))
    )
    error_message = "db_backup_start_time must be a valid UTC time in HH:MM format."
  }
}

variable "db_backup_retained_count" {
  type        = number
  description = "Number of daily automated Cloud SQL backups to retain."
  default     = 8

  validation {
    condition     = var.db_backup_retained_count >= 2 && var.db_backup_retained_count <= 365 && floor(var.db_backup_retained_count) == var.db_backup_retained_count
    error_message = "db_backup_retained_count must be a whole number from 2 through 365."
  }
}

variable "db_transaction_log_retention_days" {
  type        = number
  description = "Days of PostgreSQL transaction logs retained for point-in-time recovery."
  default     = 7

  validation {
    condition     = var.db_transaction_log_retention_days >= 1 && var.db_transaction_log_retention_days <= 7 && floor(var.db_transaction_log_retention_days) == var.db_transaction_log_retention_days
    error_message = "db_transaction_log_retention_days must be a whole number from 1 through 7 for Cloud SQL Enterprise."
  }
}

variable "db_maintenance_day" {
  type        = number
  description = "UTC maintenance day, where 1 is Monday and 7 is Sunday."
  default     = 7

  validation {
    condition     = var.db_maintenance_day >= 1 && var.db_maintenance_day <= 7 && floor(var.db_maintenance_day) == var.db_maintenance_day
    error_message = "db_maintenance_day must be a whole number from 1 through 7."
  }
}

variable "db_maintenance_hour" {
  type        = number
  description = "UTC hour at which the one-hour Cloud SQL maintenance window begins."
  default     = 8

  validation {
    condition     = var.db_maintenance_hour >= 0 && var.db_maintenance_hour <= 23 && floor(var.db_maintenance_hour) == var.db_maintenance_hour
    error_message = "db_maintenance_hour must be a whole number from 0 through 23."
  }
}

variable "db_maintenance_update_track" {
  type        = string
  description = "Cloud SQL maintenance rollout track."
  default     = "stable"

  validation {
    condition     = contains(["canary", "stable", "week5"], var.db_maintenance_update_track)
    error_message = "db_maintenance_update_track must be canary, stable, or week5."
  }
}

variable "workload_deletion_protection" {
  type        = bool
  description = "Protect Compute Engine instances and the Cloud Run job from Terraform deletion."
  default     = true
}

variable "control_machine_type" {
  type        = string
  default     = "e2-small"
  description = "The control node only dispatches. If it needs more, compute is in the wrong place."
}

variable "feed_machine_type" {
  type    = string
  default = "e2-small"
}

variable "notebook_machine_type" {
  type        = string
  default     = "n2-standard-8"
  description = "Sized for interactive comfort. Stopped when not in use."
}

variable "raw_coldline_after_days" {
  type        = number
  default     = 90
  description = "Days before current raw-data objects transition to Coldline."

  validation {
    condition     = var.raw_coldline_after_days >= 1 && floor(var.raw_coldline_after_days) == var.raw_coldline_after_days
    error_message = "raw_coldline_after_days must be a positive whole number."
  }
}

variable "log_delete_after_days" {
  type        = number
  default     = 90
  description = "Days before Airflow task-log objects are permanently deleted."

  validation {
    condition     = var.log_delete_after_days >= 1 && floor(var.log_delete_after_days) == var.log_delete_after_days
    error_message = "log_delete_after_days must be a positive whole number."
  }
}

variable "scratch_delete_after_days" {
  type        = number
  default     = 14
  description = "Days before temporary scratch objects are permanently deleted."

  validation {
    condition     = var.scratch_delete_after_days >= 1 && floor(var.scratch_delete_after_days) == var.scratch_delete_after_days
    error_message = "scratch_delete_after_days must be a positive whole number."
  }
}

variable "noncurrent_version_delete_after_days" {
  type        = number
  default     = 30
  description = "Minimum age before a noncurrent data version beyond the newest three may be deleted."

  validation {
    condition     = var.noncurrent_version_delete_after_days >= 1 && floor(var.noncurrent_version_delete_after_days) == var.noncurrent_version_delete_after_days
    error_message = "noncurrent_version_delete_after_days must be a positive whole number."
  }
}

variable "deployer_principals" {
  type        = set(string)
  description = "Named users, groups, or service accounts allowed to impersonate the Terraform deployer."

  validation {
    condition = (
      length(var.deployer_principals) > 0 &&
      alltrue([
        for principal in var.deployer_principals :
        can(regex("^(user|group|serviceAccount):[^[:space:]]+$", principal))
      ])
    )
    error_message = "deployer_principals must contain at least one user:, group:, or serviceAccount: IAM member."
  }
}

variable "operator_principals" {
  type        = set(string)
  description = "Named users or groups allowed to start, stop, and access Jarvis VMs through IAP and OS Login."

  validation {
    condition = (
      length(var.operator_principals) > 0 &&
      alltrue([
        for principal in var.operator_principals :
        can(regex("^(user|group):[^[:space:]]+$", principal))
      ])
    )
    error_message = "operator_principals must contain at least one named user: or group: IAM member."
  }
}

variable "github_repository" {
  type        = string
  description = "Exact GitHub repository in owner/name form allowed to federate."

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must use owner/name form."
  }
}

variable "github_repository_id" {
  type        = string
  description = "Immutable numeric GitHub repository ID allowed to federate."

  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_id))
    error_message = "github_repository_id must be a numeric GitHub repository ID."
  }
}

variable "github_repository_owner_id" {
  type        = string
  description = "Immutable numeric GitHub owner or organization ID allowed to federate."

  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_owner_id))
    error_message = "github_repository_owner_id must be a numeric GitHub owner ID."
  }
}

variable "github_environment" {
  type        = string
  description = "Protected GitHub environment required in the OIDC token."

  validation {
    condition     = contains(["development", "staging", "production"], var.github_environment)
    error_message = "github_environment must be development, staging, or production."
  }
}

variable "github_ref" {
  type        = string
  description = "Exact Git ref required in the GitHub OIDC token."
  default     = "refs/heads/main"

  validation {
    condition     = startswith(var.github_ref, "refs/heads/") || startswith(var.github_ref, "refs/tags/")
    error_message = "github_ref must be a full refs/heads/* or refs/tags/* ref."
  }
}
