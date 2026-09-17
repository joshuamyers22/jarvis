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
