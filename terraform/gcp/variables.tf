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
  description = "Protect the Cloud SQL instance from accidental deletion."
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
  type    = number
  default = 90
}

variable "log_delete_after_days" {
  type    = number
  default = 180
}
