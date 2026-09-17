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
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "storage" {
  for_each = aws_s3_bucket.storage

  bucket = each.value.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
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
      noncurrent_days           = 30
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
