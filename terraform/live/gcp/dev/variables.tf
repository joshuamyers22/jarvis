variable "project_id" {
  type        = string
  description = "Dedicated GCP development project ID."

  validation {
    condition = (
      can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id)) &&
      can(regex("-dev$", var.project_id))
    )
    error_message = "project_id must be valid and end in -dev."
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
  description = "Globally unique development data bucket name."
}

variable "db_tier" {
  type    = string
  default = "db-f1-micro"
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
