variable "region" {
  type    = string
  default = "us-east-1"
}

variable "env" {
  type    = string
  default = "prod"
}

variable "bucket_name" {
  type        = string
  description = "Globally unique data bucket name."

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.bucket_name))
    error_message = "bucket_name must be a valid 3-63 character S3 bucket name."
  }
}

variable "airflow_log_bucket_name" {
  type        = string
  description = "Globally unique bucket dedicated to Airflow task logs."

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.airflow_log_bucket_name))
    error_message = "airflow_log_bucket_name must be a valid 3-63 character S3 bucket name."
  }
}

variable "scratch_bucket_name" {
  type        = string
  description = "Globally unique bucket for temporary job and notebook scratch data."

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.scratch_bucket_name))
    error_message = "scratch_bucket_name must be a valid 3-63 character S3 bucket name."
  }
}

variable "backup_bucket_name" {
  type        = string
  description = "Globally unique bucket reserved for backup and restore artifacts."

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.backup_bucket_name))
    error_message = "backup_bucket_name must be a valid 3-63 character S3 bucket name."
  }
}

variable "vpc_id" {
  type        = string
  description = "Existing VPC. This module does not create networking."
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "Private subnets for Batch tasks and RDS."
}

variable "workload_egress_cidr_blocks" {
  type        = list(string)
  description = "Approved private endpoints or egress-proxy CIDRs reachable by workloads. Public default routes are forbidden."

  validation {
    condition = (
      length(var.workload_egress_cidr_blocks) > 0 &&
      alltrue([for cidr in var.workload_egress_cidr_blocks :
        can(cidrnetmask(cidr)) && !contains(["0.0.0.0/0", "::/0"], cidr)
      ])
    )
    error_message = "workload_egress_cidr_blocks must contain valid, restricted CIDRs and cannot include an unrestricted public route."
  }
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "control_instance_type" {
  type        = string
  default     = "t4g.small"
  description = "The control node only dispatches. If it needs more, compute is in the wrong place."
}

variable "feed_instance_type" {
  type    = string
  default = "t4g.small"
}

variable "notebook_instance_type" {
  type        = string
  default     = "m7g.2xlarge"
  description = "Sized for interactive comfort. Stopped when not in use."
}

variable "enable_notebook_efs" {
  type        = bool
  default     = false
  description = "Mount shared Amazon EFS storage for notebooks. Disabled preserves the local-volume default."
}

variable "notebook_efs_file_system_id" {
  type        = string
  default     = null
  nullable    = true
  description = "Existing EFS file system ID to share across environments. Leave null to create one in this stack."
}

variable "notebook_efs_access_point_id" {
  type        = string
  default     = null
  nullable    = true
  description = "Existing EFS access point ID. Required with notebook_efs_file_system_id."
}

variable "notebook_efs_mount_target_security_group_id" {
  type        = string
  default     = null
  nullable    = true
  description = "Security group on an existing EFS file system's mount targets. Required for shared EFS."
}

variable "notebook_efs_owner_account_id" {
  type        = string
  default     = null
  nullable    = true
  description = "AWS account that owns an existing shared EFS file system. Defaults to the current account."
}

variable "notebook_efs_trusted_account_ids" {
  type        = list(string)
  default     = []
  description = "Additional AWS accounts whose explicitly authorized roles may use a stack-owned notebook EFS access point."
}

variable "notebook_efs_client_security_group_ids" {
  type        = list(string)
  default     = []
  description = "Additional notebook security groups allowed to reach a stack-owned EFS mount target on TCP 2049."
}

variable "notebook_efs_transition_to_ia" {
  type        = string
  default     = "AFTER_30_DAYS"
  description = "EFS lifecycle transition for inactive notebook files."

  validation {
    condition = contains([
      "AFTER_7_DAYS",
      "AFTER_14_DAYS",
      "AFTER_30_DAYS",
      "AFTER_60_DAYS",
      "AFTER_90_DAYS",
      "AFTER_180_DAYS",
      "AFTER_270_DAYS",
      "AFTER_365_DAYS",
    ], var.notebook_efs_transition_to_ia)
    error_message = "notebook_efs_transition_to_ia must be a supported EFS lifecycle value."
  }
}

variable "raw_glacier_after_days" {
  type        = number
  default     = 90
  description = "Days before current raw-data objects transition to Glacier Instant Retrieval."

  validation {
    condition     = var.raw_glacier_after_days >= 1 && floor(var.raw_glacier_after_days) == var.raw_glacier_after_days
    error_message = "raw_glacier_after_days must be a positive whole number."
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
