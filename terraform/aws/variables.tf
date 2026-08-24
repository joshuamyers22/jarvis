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
}

variable "vpc_id" {
  type        = string
  description = "Existing VPC. This module does not create networking."
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "Private subnets for Batch tasks and RDS."
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

variable "raw_glacier_after_days" {
  type    = number
  default = 90
}

variable "log_delete_after_days" {
  type    = number
  default = 180
}
