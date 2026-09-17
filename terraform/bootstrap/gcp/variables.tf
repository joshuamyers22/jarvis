variable "project_id" {
  type        = string
  description = "Existing GCP project that owns the Terraform state bucket."

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a valid 6-30 character GCP project ID."
  }
}

variable "bucket_name" {
  type        = string
  description = "Globally unique state bucket name; lowercase letters, digits, and hyphens only."

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", var.bucket_name))
    error_message = "bucket_name must be 3-63 characters and use lowercase letters, digits, and hyphens."
  }
}

variable "location" {
  type        = string
  description = "GCS region, dual-region, or multi-region for state storage."
  default     = "US"

  validation {
    condition     = can(regex("^[A-Za-z0-9-]+$", var.location))
    error_message = "location must be a valid GCS location identifier."
  }
}

variable "state_version_retention_days" {
  type        = number
  description = "Days to retain noncurrent .tfstate generations before lifecycle deletion."
  default     = 365

  validation {
    condition     = var.state_version_retention_days >= 30 && var.state_version_retention_days <= 3650
    error_message = "state_version_retention_days must be between 30 days and 10 years."
  }
}

variable "soft_delete_retention_days" {
  type        = number
  description = "Recovery window for deleted bucket objects. GCS supports 7-90 days."
  default     = 14

  validation {
    condition     = var.soft_delete_retention_days >= 7 && var.soft_delete_retention_days <= 90
    error_message = "soft_delete_retention_days must be between 7 and 90."
  }
}

variable "state_writer_principals" {
  type        = set(string)
  description = "IAM members allowed to read and write state objects, normally environment deployer service accounts."

  validation {
    condition = length(var.state_writer_principals) > 0 && alltrue([
      for principal in var.state_writer_principals :
      can(regex("^(user|group|serviceAccount|domain|principal|principalSet):.+$", principal))
    ])
    error_message = "Provide at least one valid, non-public IAM member as a state writer."
  }
}

variable "state_reader_principals" {
  type        = set(string)
  description = "IAM members allowed read-only access to state objects for audit or recovery."
  default     = []

  validation {
    condition = alltrue([
      for principal in var.state_reader_principals :
      can(regex("^(user|group|serviceAccount|domain|principal|principalSet):.+$", principal))
    ])
    error_message = "Every state reader must be a valid, non-public IAM member."
  }
}

variable "bucket_admin_principals" {
  type        = set(string)
  description = "IAM members allowed to administer this bucket only, normally a platform administrator group."

  validation {
    condition = length(var.bucket_admin_principals) > 0 && alltrue([
      for principal in var.bucket_admin_principals :
      can(regex("^(user|group|serviceAccount|domain|principal|principalSet):.+$", principal))
    ])
    error_message = "Provide at least one valid, non-public IAM member as a bucket administrator."
  }
}

variable "labels" {
  type        = map(string)
  description = "Additional labels merged with the required bootstrap labels."
  default     = {}
}
