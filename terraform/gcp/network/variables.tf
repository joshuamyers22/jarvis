variable "project_id" {
  type        = string
  description = "GCP project that owns this isolated network."

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a valid 6-30 character GCP project ID."
  }
}

variable "env" {
  type        = string
  description = "Deployment environment."

  validation {
    condition     = contains(["dev", "stage", "prod"], var.env)
    error_message = "env must be dev, stage, or prod."
  }
}

variable "region" {
  type        = string
  description = "Region for the workload subnet, router, and NAT gateway."
}

variable "labels" {
  type        = map(string)
  description = "Additional ownership and cost-allocation labels. Required network identity labels cannot be overridden."
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

variable "subnet_cidr" {
  type        = string
  description = "Primary IPv4 CIDR for private workload instances."

  validation {
    condition     = can(cidrnetmask(var.subnet_cidr))
    error_message = "subnet_cidr must be a valid IPv4 CIDR."
  }
}

variable "private_service_address" {
  type        = string
  description = "Network address reserved for private services access."

  validation {
    condition     = can(cidrnetmask("${var.private_service_address}/32"))
    error_message = "private_service_address must be a valid IPv4 network address without a prefix."
  }
}

variable "private_service_prefix_length" {
  type        = number
  description = "Prefix length of the private services allocation."
  default     = 20

  validation {
    condition     = var.private_service_prefix_length >= 16 && var.private_service_prefix_length <= 24
    error_message = "private_service_prefix_length must be between /16 and /24."
  }
}
