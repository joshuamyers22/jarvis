variable "project_id" {
  type        = string
  description = "GCP project id."
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
  type    = string
  default = "prod"
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
