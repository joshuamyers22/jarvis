variable "project_id" {
  type        = string
  description = "Dedicated GCP staging project ID."

  validation {
    condition = (
      can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id)) &&
      can(regex("-stage$", var.project_id))
    )
    error_message = "project_id must be valid and end in -stage."
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

variable "bucket_name" {
  type        = string
  description = "Globally unique staging data bucket name."
}

variable "airflow_log_bucket_name" {
  type        = string
  description = "Globally unique staging Airflow-log bucket name."
}

variable "scratch_bucket_name" {
  type        = string
  description = "Globally unique staging scratch bucket name."
}

variable "backup_bucket_name" {
  type        = string
  description = "Globally unique staging backup bucket name."
}

variable "billing_account_id" {
  type        = string
  description = "Cloud Billing account that owns the staging budget."
}

variable "alert_email" {
  type        = string
  description = "Operational recipient for staging budget and quota alerts."
}

variable "monthly_budget_usd" {
  type        = number
  description = "Approved whole-dollar monthly staging budget."
}

variable "deployer_principals" {
  type        = set(string)
  description = "Named principals allowed to impersonate the staging Terraform deployer."
}

variable "operator_principals" {
  type        = set(string)
  description = "Named users or groups allowed to operate staging VMs through IAP and OS Admin Login."
}

variable "github_repository" {
  type        = string
  description = "Exact GitHub repository in owner/name form."
}

variable "github_repository_id" {
  type        = string
  description = "Immutable numeric GitHub repository ID."
}

variable "github_repository_owner_id" {
  type        = string
  description = "Immutable numeric GitHub owner ID."
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
  description = "Approved cross-project Cloud Storage grants. Empty means default deny."
  default     = {}
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
  description = "Approved cross-project BigQuery grants. Empty means default deny."
  default     = {}
}

variable "db_tier" {
  type    = string
  default = "db-g1-small"
}

variable "control_machine_type" {
  type    = string
  default = "e2-small"
}

variable "feed_machine_type" {
  type    = string
  default = "e2-small"
}

variable "notebook_machine_type" {
  type    = string
  default = "n2-standard-4"
}

variable "host_images" {
  type = object({
    control  = string
    feed     = string
    notebook = string
  })
  description = "Reviewed immutable host image references for staging VMs."
}

variable "host_replacement_role" {
  type        = string
  description = "One VM role approved for host image replacement."
  default     = null
  nullable    = true
}
