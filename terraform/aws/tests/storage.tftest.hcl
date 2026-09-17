mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
      arn        = "arn:aws:iam::123456789012:user/test"
      id         = "123456789012"
    }
  }

  mock_data "aws_partition" {
    defaults = {
      partition  = "aws"
      dns_suffix = "amazonaws.com"
    }
  }

  mock_data "aws_subnet" {
    defaults = {
      availability_zone = "us-east-1a"
    }
  }

  mock_data "aws_ami" {
    defaults = {
      id = "ami-1234567890abcdef0"
    }
  }

  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{}"
    }
  }

  mock_resource "aws_batch_compute_environment" {
    defaults = {
      arn = "arn:aws:batch:us-east-1:123456789012:compute-environment/research-prod"
    }
  }
}

mock_provider "random" {}

variables {
  bucket_name                 = "jarvis-research-prod-data"
  airflow_log_bucket_name     = "jarvis-research-prod-airflow-logs"
  scratch_bucket_name         = "jarvis-research-prod-scratch"
  backup_bucket_name          = "jarvis-research-prod-backup"
  vpc_id                      = "vpc-12345678"
  private_subnet_ids          = ["subnet-12345678"]
  workload_egress_cidr_blocks = ["10.0.0.0/8"]
}

run "storage_boundaries_are_private_and_distinct" {
  command = apply

  assert {
    condition = (
      aws_s3_bucket.data.bucket == "jarvis-research-prod-data" &&
      aws_s3_bucket.storage["airflow_logs"].bucket == "jarvis-research-prod-airflow-logs" &&
      aws_s3_bucket.storage["scratch"].bucket == "jarvis-research-prod-scratch" &&
      aws_s3_bucket.storage["backup"].bucket == "jarvis-research-prod-backup"
    )
    error_message = "AWS must provision separate data, log, scratch, and backup buckets."
  }

  assert {
    condition = (
      aws_ecr_repository.images.image_tag_mutability == "IMMUTABLE" &&
      alltrue([for key in values(aws_kms_key.storage) : key.enable_key_rotation]) &&
      one(aws_s3_bucket_server_side_encryption_configuration.data.rule).apply_server_side_encryption_by_default[0].sse_algorithm == "aws:kms" &&
      alltrue([for boundary in values(aws_s3_bucket_server_side_encryption_configuration.storage) :
        one(boundary.rule).apply_server_side_encryption_by_default[0].sse_algorithm == "aws:kms"
      ]) &&
      aws_instance.control.metadata_options[0].http_tokens == "required" &&
      aws_instance.feed.metadata_options[0].http_tokens == "required" &&
      aws_instance.notebook.metadata_options[0].http_tokens == "required"
    )
    error_message = "AWS storage, images, and instance metadata must use the hardened production defaults."
  }

  assert {
    condition = (
      aws_s3_bucket_public_access_block.data.block_public_acls &&
      aws_s3_bucket_public_access_block.data.block_public_policy &&
      aws_s3_bucket_public_access_block.data.ignore_public_acls &&
      aws_s3_bucket_public_access_block.data.restrict_public_buckets &&
      alltrue(flatten([
        for boundary in values(aws_s3_bucket_public_access_block.storage) : [
          boundary.block_public_acls,
          boundary.block_public_policy,
          boundary.ignore_public_acls,
          boundary.restrict_public_buckets,
        ]
      ]))
    )
    error_message = "Every S3 boundary must block all forms of public access."
  }

  assert {
    condition = (
      aws_s3_bucket_versioning.data.versioning_configuration[0].status == "Enabled" &&
      aws_s3_bucket_versioning.storage["airflow_logs"].versioning_configuration[0].status == "Suspended" &&
      aws_s3_bucket_versioning.storage["scratch"].versioning_configuration[0].status == "Suspended" &&
      aws_s3_bucket_versioning.storage["backup"].versioning_configuration[0].status == "Enabled"
    )
    error_message = "Durable data and backup storage must be versioned while operational storage is not."
  }

  assert {
    condition = (
      output.storage_lifecycle_policy.policy_version == "1" &&
      output.storage_lifecycle_policy.raw.transition_after_days == 90 &&
      !output.storage_lifecycle_policy.raw.delete_current &&
      output.storage_lifecycle_policy.noncurrent_data_versions.retained_count == 3 &&
      output.storage_lifecycle_policy.noncurrent_data_versions.minimum_age_days == 30 &&
      output.storage_lifecycle_policy.airflow_logs.delete_after_days == 90 &&
      output.storage_lifecycle_policy.scratch.delete_after_days == 14 &&
      output.storage_lifecycle_policy.backup.delete_after_days == null &&
      one(aws_s3_bucket_lifecycle_configuration.scratch.rule).expiration[0].days == 14 &&
      one(flatten([
        for rule in aws_s3_bucket_lifecycle_configuration.data.rule : [
          for expiration in rule.noncurrent_version_expiration : expiration.newer_noncurrent_versions
        ]
      ])) == 3
    )
    error_message = "AWS must enforce the approved raw, version, log, scratch, and backup lifecycle policy."
  }

  assert {
    condition = (
      aws_iam_role_policy.control_logs.role == aws_iam_role.roles["control"].id &&
      aws_iam_role_policy.job_data.role == aws_iam_role.roles["job"].id &&
      aws_iam_role_policy.feed_data.role == aws_iam_role.roles["feed"].id &&
      aws_iam_role_policy.notebook_data.role == aws_iam_role.roles["notebook"].id &&
      aws_iam_role_policy.job_scratch.role == aws_iam_role.roles["job"].id &&
      aws_iam_role_policy.notebook_scratch.role == aws_iam_role.roles["notebook"].id
    )
    error_message = "Storage policies must attach only to their intended workload roles."
  }

  assert {
    condition = (
      toset(keys(output.storage_locations)) == toset(["data", "airflow_logs", "scratch", "backup"]) &&
      length(output.storage_contract.backup.workload_access) == 0 &&
      toset(keys(output.storage_contract.data.workload_access)) == toset(["job", "feed", "notebook"]) &&
      toset(keys(output.storage_contract.airflow_logs.workload_access)) == toset(["control"]) &&
      toset(keys(output.storage_contract.scratch.workload_access)) == toset(["job", "notebook"])
    )
    error_message = "The AWS storage contract must expose the intended workload boundary and no backup runtime access."
  }
}

run "duplicate_storage_boundaries_are_rejected" {
  command = plan

  variables {
    backup_bucket_name = "jarvis-research-prod-data"
  }

  expect_failures = [aws_s3_bucket.data]
}
