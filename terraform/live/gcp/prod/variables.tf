variable "project_id" {
  type        = string
  description = "Dedicated GCP production project ID."

  validation {
    condition = (
      can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id)) &&
      can(regex("-prod$", var.project_id))
    )
    error_message = "project_id must be valid and end in -prod."
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
  description = "Globally unique production data bucket name."
}

variable "db_tier" {
  type    = string
  default = "db-custom-2-7680"
}

variable "control_machine_type" {
  type    = string
  default = "e2-standard-2"
}

variable "feed_machine_type" {
  type    = string
  default = "e2-standard-2"
}

variable "notebook_machine_type" {
  type    = string
  default = "n2-standard-8"
}
