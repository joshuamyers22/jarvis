resource "aws_s3_bucket" "data" {
  bucket = var.bucket_name
  tags   = merge(local.common_tags, { StoragePurpose = "data" })

  lifecycle {
    precondition {
      condition = length(toset([
        var.bucket_name,
        var.airflow_log_bucket_name,
        var.scratch_bucket_name,
        var.backup_bucket_name,
      ])) == 4
      error_message = "Data, Airflow-log, scratch, and backup buckets must use distinct names."
    }
  }
}

locals {
  additional_storage_buckets = {
    airflow_logs = var.airflow_log_bucket_name
    scratch      = var.scratch_bucket_name
    backup       = var.backup_bucket_name
  }
  storage_kms_keys = toset(["data", "airflow_logs", "scratch", "backup"])
}

resource "aws_kms_key" "storage" {
  for_each = local.storage_kms_keys

  description             = "${local.name_prefix} ${replace(each.key, "_", " ")} storage encryption"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  tags                    = merge(local.common_tags, { StoragePurpose = each.key })
}

resource "aws_kms_alias" "storage" {
  for_each = aws_kms_key.storage

  name          = "alias/${local.name_prefix}-${replace(each.key, "_", "-")}-storage"
  target_key_id = each.value.key_id
}

resource "aws_s3_bucket" "storage" {
  for_each = local.additional_storage_buckets

  bucket = each.value
  tags   = merge(local.common_tags, { StoragePurpose = each.key })
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_public_access_block" "storage" {
  for_each = aws_s3_bucket.storage

  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_versioning" "storage" {
  for_each = aws_s3_bucket.storage

  bucket = each.value.id
  versioning_configuration {
    status = each.key == "backup" ? "Enabled" : "Suspended"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.storage["data"].arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "storage" {
  for_each = aws_s3_bucket.storage

  bucket = each.value.id
  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.storage[each.key].arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  # Raw data is rarely re-read once derived exists, but must never be deleted:
  # it is the only thing that cannot be recomputed.
  rule {
    id     = "raw-to-glacier"
    status = "Enabled"
    filter { prefix = "raw/" }
    transition {
      days          = var.raw_glacier_after_days
      storage_class = "GLACIER_IR"
    }
  }

  # Noncurrent versions exist to undo a bad overwrite, not as an archive.
  rule {
    id     = "prune-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      newer_noncurrent_versions = 3
      noncurrent_days           = var.noncurrent_version_delete_after_days
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "airflow_logs" {
  bucket = aws_s3_bucket.storage["airflow_logs"].id

  rule {
    id     = "expire-logs"
    status = "Enabled"
    filter {}
    expiration { days = var.log_delete_after_days }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "scratch" {
  bucket = aws_s3_bucket.storage["scratch"].id

  rule {
    id     = "expire-scratch"
    status = "Enabled"
    filter {}
    expiration { days = var.scratch_delete_after_days }
  }
}

locals {
  storage_lifecycle_policy = {
    policy_version = "1"
    raw = {
      prefix                = "raw/"
      transition_after_days = var.raw_glacier_after_days
      transition_tier       = "GLACIER_IR"
      delete_current        = false
    }
    noncurrent_data_versions = {
      retained_count   = 3
      minimum_age_days = var.noncurrent_version_delete_after_days
      enforcement      = "count-and-minimum-age"
    }
    delete_recovery = {
      minimum_age_days = var.noncurrent_version_delete_after_days
      enforcement      = "object-versioning"
    }
    airflow_logs = {
      delete_after_days = var.log_delete_after_days
    }
    scratch = {
      delete_after_days = var.scratch_delete_after_days
    }
    backup = {
      delete_after_days = null
    }
    provider_limitations = []
  }
}
